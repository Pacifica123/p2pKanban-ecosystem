use std::{
    collections::BTreeSet,
    io::{Read, Write},
    net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream},
    ptr,
    sync::{
        atomic::{AtomicBool, AtomicU32, AtomicU8, Ordering},
        Arc, Mutex,
    },
    thread::{self, JoinHandle},
    time::{Duration, Instant, SystemTime, UNIX_EPOCH},
};

use crate::{
    application::lan_bridge::{
        LanBridgeHandle, LanBridgePayloadHandler, LanBridgeRuntime, LanBridgeRuntimeError,
    },
    domain::lan_bridge::{
        open_lan_bridge_envelope, LanBridgeLifecycle, LanBridgeStartRequest, LanBridgeStatus, LAN_BRIDGE_MAX_ATTEMPTS,
        LAN_BRIDGE_MAX_HEADER_BYTES, LAN_BRIDGE_MAX_HTTP_BODY_BYTES, LAN_BRIDGE_PATH,
        LAN_BRIDGE_TOKEN_BYTES,
    },
};

const HIGH_PORT_MIN: u16 = 49_152;
const HIGH_PORT_SPAN: u32 = (u16::MAX as u32) - (HIGH_PORT_MIN as u32) + 1;
const ACCEPT_POLL: Duration = Duration::from_millis(25);
const CLIENT_TIMEOUT: Duration = Duration::from_secs(2);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RequestFailure {
    BadRequest,
    Forbidden,
    NotFound,
    MethodNotAllowed,
    UnsupportedMediaType,
    TooLarge,
    AuthenticationFailed,
}

impl RequestFailure {
    const fn response(self) -> (u16, &'static str, &'static str) {
        match self {
            Self::BadRequest => (400, "Bad Request", "bad-request"),
            Self::Forbidden => (403, "Forbidden", "forbidden"),
            Self::NotFound => (404, "Not Found", "not-found"),
            Self::MethodNotAllowed => (405, "Method Not Allowed", "method-not-allowed"),
            Self::UnsupportedMediaType => (415, "Unsupported Media Type", "unsupported-media-type"),
            Self::TooLarge => (413, "Payload Too Large", "payload-too-large"),
            Self::AuthenticationFailed => (401, "Unauthorized", "authentication-failed"),
        }
    }
}

struct SharedBridgeState {
    lifecycle: AtomicU8,
    attempts: AtomicU32,
    stop: AtomicBool,
    bind_address: String,
    endpoint: String,
    expires_at_unix: i64,
    last_result: Mutex<Option<String>>,
}

impl SharedBridgeState {
    fn new(local_addr: SocketAddr, ttl_secs: u64) -> Self {
        let expires_at_unix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|duration| duration.as_secs() as i64 + ttl_secs as i64)
            .unwrap_or(ttl_secs as i64);
        Self {
            lifecycle: AtomicU8::new(lifecycle_code(LanBridgeLifecycle::Listening)),
            attempts: AtomicU32::new(0),
            stop: AtomicBool::new(false),
            bind_address: local_addr.to_string(),
            endpoint: format!("http://{local_addr}{LAN_BRIDGE_PATH}"),
            expires_at_unix,
            last_result: Mutex::new(None),
        }
    }

    fn set_terminal(&self, lifecycle: LanBridgeLifecycle, result: impl Into<String>) {
        self.lifecycle.store(lifecycle_code(lifecycle), Ordering::SeqCst);
        if let Ok(mut last) = self.last_result.lock() {
            *last = Some(result.into());
        }
        self.stop.store(true, Ordering::SeqCst);
    }

    fn status(&self) -> LanBridgeStatus {
        LanBridgeStatus {
            lifecycle: lifecycle_from_code(self.lifecycle.load(Ordering::SeqCst)),
            bind_address: Some(self.bind_address.clone()),
            endpoint: Some(self.endpoint.clone()),
            expires_at_unix: Some(self.expires_at_unix),
            attempts: self.attempts.load(Ordering::SeqCst),
            last_result: self
                .last_result
                .lock()
                .ok()
                .and_then(|value| value.clone()),
        }
    }
}

const fn lifecycle_code(value: LanBridgeLifecycle) -> u8 {
    match value {
        LanBridgeLifecycle::Stopped => 0,
        LanBridgeLifecycle::Listening => 1,
        LanBridgeLifecycle::Completed => 2,
        LanBridgeLifecycle::Expired => 3,
        LanBridgeLifecycle::Failed => 4,
    }
}

const fn lifecycle_from_code(value: u8) -> LanBridgeLifecycle {
    match value {
        1 => LanBridgeLifecycle::Listening,
        2 => LanBridgeLifecycle::Completed,
        3 => LanBridgeLifecycle::Expired,
        4 => LanBridgeLifecycle::Failed,
        _ => LanBridgeLifecycle::Stopped,
    }
}

fn is_supported_bind_address(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(value) => value.is_private() || value.is_link_local() || value.is_loopback(),
        IpAddr::V6(_) => false,
    }
}

fn is_user_lan_address(address: IpAddr) -> bool {
    match address {
        IpAddr::V4(value) => value.is_private() || value.is_link_local(),
        IpAddr::V6(_) => false,
    }
}

pub struct LinuxLanBridgeRuntime {
    allow_loopback: bool,
}

impl LinuxLanBridgeRuntime {
    pub const fn production() -> Self {
        Self { allow_loopback: false }
    }

    pub const fn host_probe() -> Self {
        Self { allow_loopback: true }
    }

    fn address_allowed(&self, address: IpAddr) -> bool {
        is_user_lan_address(address) || (self.allow_loopback && address.is_loopback())
    }
}

impl LanBridgeRuntime for LinuxLanBridgeRuntime {
    fn available_bind_addresses(&self) -> Vec<String> {
        let mut addresses = linux_ipv4_addresses();
        if self.allow_loopback {
            addresses.push(IpAddr::V4(Ipv4Addr::LOCALHOST));
        }
        addresses.retain(|address| self.address_allowed(*address));
        addresses.sort();
        addresses.dedup();
        addresses.into_iter().map(|address| address.to_string()).collect()
    }

    fn start(
        &self,
        request: LanBridgeStartRequest,
        mut token: [u8; LAN_BRIDGE_TOKEN_BYTES],
        handler: LanBridgePayloadHandler,
    ) -> Result<Box<dyn LanBridgeHandle>, LanBridgeRuntimeError> {
        let bind_address: IpAddr = request
            .bind_address
            .parse()
            .map_err(|_| LanBridgeRuntimeError::UnsupportedAddress)?;
        if !is_supported_bind_address(bind_address) || !self.address_allowed(bind_address) {
            return Err(LanBridgeRuntimeError::UnsupportedAddress);
        }
        let listener = bind_random_high_port(bind_address)?;
        listener
            .set_nonblocking(true)
            .map_err(|_| LanBridgeRuntimeError::Io)?;
        let local_addr = listener.local_addr().map_err(|_| LanBridgeRuntimeError::Io)?;
        let state = Arc::new(SharedBridgeState::new(local_addr, request.ttl_secs));
        let thread_state = Arc::clone(&state);
        let deadline = Instant::now() + Duration::from_secs(request.ttl_secs);
        let join = thread::Builder::new()
            .name("p2pkanban-lan-bridge".into())
            .spawn(move || {
                while !thread_state.stop.load(Ordering::SeqCst) {
                    if Instant::now() >= deadline {
                        thread_state.set_terminal(LanBridgeLifecycle::Expired, "ttl-expired");
                        break;
                    }
                    match listener.accept() {
                        Ok((mut stream, peer)) => {
                            if !peer.ip().is_loopback() && !is_user_lan_address(peer.ip()) {
                                let _ = write_failure(&mut stream, RequestFailure::Forbidden);
                                continue;
                            }
                            let attempts = thread_state.attempts.fetch_add(1, Ordering::SeqCst) + 1;
                            if attempts > LAN_BRIDGE_MAX_ATTEMPTS {
                                let _ = write_json_response(&mut stream, 429, "Too Many Requests", r#"{"status":"rate-limited"}"#);
                                thread_state.set_terminal(LanBridgeLifecycle::Failed, "rate-limit-exhausted");
                                break;
                            }
                            let request_body = match read_http_request(&mut stream, local_addr) {
                                Ok(body) => body,
                                Err(error) => {
                                    let _ = write_failure(&mut stream, error);
                                    continue;
                                }
                            };
                            let plaintext = match open_lan_bridge_envelope(&request_body, &token) {
                                Ok(value) => value,
                                Err(_) => {
                                    let _ = write_failure(&mut stream, RequestFailure::AuthenticationFailed);
                                    continue;
                                }
                            };

                            // Authentication succeeded: the capability is one-time. The bridge
                            // closes after this request regardless of semantic import success.
                            match handler(&plaintext) {
                                Ok(body) => {
                                    let safe_body = if body.len() <= 8 * 1024 { body } else { r#"{"status":"accepted"}"#.to_owned() };
                                    let _ = write_json_response(&mut stream, 200, "OK", &safe_body);
                                    thread_state.set_terminal(LanBridgeLifecycle::Completed, "accepted-once");
                                }
                                Err(code) => {
                                    let body = serde_json::json!({"status":"rejected","code": sanitize_result_code(&code)}).to_string();
                                    let _ = write_json_response(&mut stream, 422, "Unprocessable Content", &body);
                                    thread_state.set_terminal(LanBridgeLifecycle::Failed, "authenticated-payload-rejected");
                                }
                            }
                            break;
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            thread::sleep(ACCEPT_POLL);
                        }
                        Err(_) => {
                            thread_state.set_terminal(LanBridgeLifecycle::Failed, "listener-io-failure");
                            break;
                        }
                    }
                }
                token.fill(0);
            })
            .map_err(|_| LanBridgeRuntimeError::Io)?;

        Ok(Box::new(LinuxLanBridgeHandle {
            state,
            join: Mutex::new(Some(join)),
        }))
    }
}

struct LinuxLanBridgeHandle {
    state: Arc<SharedBridgeState>,
    join: Mutex<Option<JoinHandle<()>>>,
}

impl LanBridgeHandle for LinuxLanBridgeHandle {
    fn status(&self) -> LanBridgeStatus {
        self.state.status()
    }

    fn stop(&self) -> Result<(), LanBridgeRuntimeError> {
        let prior = lifecycle_from_code(self.state.lifecycle.load(Ordering::SeqCst));
        if prior == LanBridgeLifecycle::Listening {
            self.state.stop.store(true, Ordering::SeqCst);
            self.state.lifecycle.store(lifecycle_code(LanBridgeLifecycle::Stopped), Ordering::SeqCst);
            if let Ok(mut last) = self.state.last_result.lock() {
                *last = Some("manual-stop".to_owned());
            }
        }
        let mut join = self.join.lock().map_err(|_| LanBridgeRuntimeError::Io)?;
        if let Some(thread) = join.take() {
            thread.join().map_err(|_| LanBridgeRuntimeError::Io)?;
        }
        Ok(())
    }
}

impl Drop for LinuxLanBridgeHandle {
    fn drop(&mut self) {
        self.state.stop.store(true, Ordering::SeqCst);
        if lifecycle_from_code(self.state.lifecycle.load(Ordering::SeqCst)) == LanBridgeLifecycle::Listening {
            self.state.lifecycle.store(lifecycle_code(LanBridgeLifecycle::Stopped), Ordering::SeqCst);
        }
        if let Ok(join) = self.join.get_mut() {
            if let Some(thread) = join.take() {
                let _ = thread.join();
            }
        }
    }
}

fn bind_random_high_port(address: IpAddr) -> Result<TcpListener, LanBridgeRuntimeError> {
    for _ in 0..32 {
        let mut random = [0_u8; 2];
        getrandom::fill(&mut random).map_err(|_| LanBridgeRuntimeError::Io)?;
        let offset = u16::from_be_bytes(random) as u32 % HIGH_PORT_SPAN;
        let port = HIGH_PORT_MIN + offset as u16;
        match TcpListener::bind(SocketAddr::new(address, port)) {
            Ok(listener) => return Ok(listener),
            Err(error) if error.kind() == std::io::ErrorKind::AddrInUse => continue,
            Err(_) => return Err(LanBridgeRuntimeError::BindUnavailable),
        }
    }
    Err(LanBridgeRuntimeError::BindUnavailable)
}

fn read_http_request(stream: &mut TcpStream, local_addr: SocketAddr) -> Result<Vec<u8>, RequestFailure> {
    stream.set_read_timeout(Some(CLIENT_TIMEOUT)).map_err(|_| RequestFailure::BadRequest)?;
    stream.set_write_timeout(Some(CLIENT_TIMEOUT)).map_err(|_| RequestFailure::BadRequest)?;

    let mut received = Vec::with_capacity(4096);
    let header_end = loop {
        if received.len() > LAN_BRIDGE_MAX_HEADER_BYTES {
            return Err(RequestFailure::TooLarge);
        }
        if let Some(position) = find_header_end(&received) {
            break position;
        }
        let mut chunk = [0_u8; 2048];
        let count = stream.read(&mut chunk).map_err(|_| RequestFailure::BadRequest)?;
        if count == 0 {
            return Err(RequestFailure::BadRequest);
        }
        received.extend_from_slice(&chunk[..count]);
    };

    let head = std::str::from_utf8(&received[..header_end]).map_err(|_| RequestFailure::BadRequest)?;
    let mut lines = head.split("\r\n");
    let request_line = lines.next().ok_or(RequestFailure::BadRequest)?;
    let mut request_parts = request_line.split(' ');
    let method = request_parts.next().ok_or(RequestFailure::BadRequest)?;
    let path = request_parts.next().ok_or(RequestFailure::BadRequest)?;
    let version = request_parts.next().ok_or(RequestFailure::BadRequest)?;
    if request_parts.next().is_some() || version != "HTTP/1.1" {
        return Err(RequestFailure::BadRequest);
    }
    if method != "POST" {
        return Err(RequestFailure::MethodNotAllowed);
    }
    if path != LAN_BRIDGE_PATH {
        return Err(RequestFailure::NotFound);
    }

    let mut host: Option<&str> = None;
    let mut content_type: Option<&str> = None;
    let mut content_length: Option<usize> = None;
    for line in lines {
        if line.is_empty() {
            continue;
        }
        let (name, value) = line.split_once(':').ok_or(RequestFailure::BadRequest)?;
        let name = name.trim().to_ascii_lowercase();
        let value = value.trim();
        match name.as_str() {
            "host" => {
                if host.replace(value).is_some() { return Err(RequestFailure::BadRequest); }
            }
            "content-type" => {
                if content_type.replace(value).is_some() { return Err(RequestFailure::BadRequest); }
            }
            "content-length" => {
                if content_length.is_some() { return Err(RequestFailure::BadRequest); }
                content_length = Some(value.parse().map_err(|_| RequestFailure::BadRequest)?);
            }
            "origin" | "cookie" | "authorization" | "proxy-authorization" => return Err(RequestFailure::Forbidden),
            "transfer-encoding" => return Err(RequestFailure::BadRequest),
            "connection" | "user-agent" | "accept" | "accept-encoding" => {}
            _ => return Err(RequestFailure::BadRequest),
        }
    }
    let expected_host = local_addr.to_string();
    if host != Some(expected_host.as_str()) {
        return Err(RequestFailure::Forbidden);
    }
    if content_type != Some("application/json") {
        return Err(RequestFailure::UnsupportedMediaType);
    }
    let content_length = content_length.ok_or(RequestFailure::BadRequest)?;
    if content_length == 0 || content_length > LAN_BRIDGE_MAX_HTTP_BODY_BYTES {
        return Err(RequestFailure::TooLarge);
    }

    let body_start = header_end + 4;
    let mut body = Vec::with_capacity(content_length);
    if received.len() > body_start {
        let already = &received[body_start..];
        if already.len() > content_length {
            return Err(RequestFailure::BadRequest);
        }
        body.extend_from_slice(already);
    }
    while body.len() < content_length {
        let remaining = content_length - body.len();
        let mut chunk = [0_u8; 8192];
        let take = remaining.min(chunk.len());
        let count = stream
            .read(&mut chunk[..take])
            .map_err(|_| RequestFailure::BadRequest)?;
        if count == 0 {
            return Err(RequestFailure::BadRequest);
        }
        body.extend_from_slice(&chunk[..count]);
    }
    Ok(body)
}

fn find_header_end(bytes: &[u8]) -> Option<usize> {
    bytes.windows(4).position(|window| window == b"\r\n\r\n")
}

fn write_failure(stream: &mut TcpStream, error: RequestFailure) -> std::io::Result<()> {
    let (status, reason, code) = error.response();
    let body = serde_json::json!({"status":"rejected","code":code}).to_string();
    write_json_response(stream, status, reason, &body)
}

fn write_json_response(stream: &mut TcpStream, status: u16, reason: &str, body: &str) -> std::io::Result<()> {
    let response = format!(
        "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\nX-Content-Type-Options: nosniff\r\n\r\n{body}",
        body.as_bytes().len()
    );
    stream.write_all(response.as_bytes())?;
    stream.flush()
}

fn sanitize_result_code(value: &str) -> String {
    let trimmed = value.trim();
    if trimmed.is_empty() || trimmed.len() > 64 {
        return "rejected".to_owned();
    }
    if !trimmed.bytes().all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-') {
        return "rejected".to_owned();
    }
    trimmed.to_owned()
}

fn linux_ipv4_addresses() -> Vec<IpAddr> {
    let mut result = BTreeSet::new();
    let mut head: *mut libc::ifaddrs = ptr::null_mut();
    // SAFETY: getifaddrs initializes a linked list owned by libc; every pointer is
    // read only while the list is alive and the matching freeifaddrs is always called.
    if unsafe { libc::getifaddrs(&mut head) } != 0 || head.is_null() {
        return Vec::new();
    }
    let mut current = head;
    while !current.is_null() {
        // SAFETY: current is an element from the live getifaddrs list.
        let entry = unsafe { &*current };
        if !entry.ifa_addr.is_null()
            && (entry.ifa_flags & libc::IFF_UP as u32) != 0
            // SAFETY: ifa_addr is non-null and sa_family is part of sockaddr header.
            && unsafe { (*entry.ifa_addr).sa_family as i32 } == libc::AF_INET
        {
            // SAFETY: AF_INET guarantees sockaddr_in layout for this entry.
            let socket = unsafe { &*(entry.ifa_addr as *const libc::sockaddr_in) };
            let octets = socket.sin_addr.s_addr.to_ne_bytes();
            let address = IpAddr::V4(Ipv4Addr::from(octets));
            if is_user_lan_address(address) {
                result.insert(address);
            }
        }
        current = entry.ifa_next;
    }
    // SAFETY: head is the original pointer returned by getifaddrs above.
    unsafe { libc::freeifaddrs(head) };
    result.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use std::{io::{Read, Write}, sync::atomic::{AtomicUsize, Ordering}};

    use super::*;
    use crate::domain::lan_bridge::{seal_lan_bridge_payload, LAN_BRIDGE_NONCE_BYTES};

    fn post(addr: SocketAddr, body: &[u8], extra_headers: &str) -> String {
        let mut stream = TcpStream::connect(addr).unwrap();
        let request = format!(
            "POST {LAN_BRIDGE_PATH} HTTP/1.1\r\nHost: {addr}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n{extra_headers}\r\n",
            body.len()
        );
        stream.write_all(request.as_bytes()).unwrap();
        stream.write_all(body).unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).unwrap();
        response
    }

    #[test]
    fn a14_bind_scope_is_private_link_local_or_probe_loopback_only() {
        for address in ["192.168.1.4", "10.0.0.8", "172.20.2.3", "169.254.5.1", "127.0.0.1"] {
            assert!(is_supported_bind_address(address.parse().unwrap()));
        }
        for address in ["0.0.0.0", "8.8.8.8", "1.1.1.1", "::", "::1"] {
            assert!(!is_supported_bind_address(address.parse().unwrap()));
        }
        let production = LinuxLanBridgeRuntime::production();
        assert!(!production.address_allowed("127.0.0.1".parse().unwrap()));
        let probe = LinuxLanBridgeRuntime::host_probe();
        assert!(probe.address_allowed("127.0.0.1".parse().unwrap()));
    }

    #[test]
    fn a14_transport_accepts_one_authenticated_payload_then_closes() {
        let runtime = LinuxLanBridgeRuntime::host_probe();
        let token = [3_u8; LAN_BRIDGE_TOKEN_BYTES];
        let nonce = [4_u8; LAN_BRIDGE_NONCE_BYTES];
        let calls = Arc::new(AtomicUsize::new(0));
        let handler_calls = Arc::clone(&calls);
        let handler: LanBridgePayloadHandler = Arc::new(move |payload| {
            assert_eq!(payload, br#"{"kind":"probe"}"#);
            handler_calls.fetch_add(1, Ordering::SeqCst);
            Ok(r#"{"status":"accepted"}"#.to_owned())
        });
        let handle = runtime
            .start(LanBridgeStartRequest::validated("127.0.0.1", 30).unwrap(), token, handler)
            .unwrap();
        let addr: SocketAddr = handle.status().bind_address.unwrap().parse().unwrap();
        let envelope = seal_lan_bridge_payload(br#"{"kind":"probe"}"#, &token, &nonce).unwrap();
        let response = post(addr, &envelope, "");
        assert!(response.starts_with("HTTP/1.1 200 OK"));
        for _ in 0..50 {
            if handle.status().lifecycle != LanBridgeLifecycle::Listening { break; }
            thread::sleep(Duration::from_millis(10));
        }
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(handle.status().lifecycle, LanBridgeLifecycle::Completed);
    }

    #[test]
    fn a14_transport_rejects_origin_host_confusion_and_wrong_capability() {
        let runtime = LinuxLanBridgeRuntime::host_probe();
        let token = [5_u8; LAN_BRIDGE_TOKEN_BYTES];
        let nonce = [6_u8; LAN_BRIDGE_NONCE_BYTES];
        let handler: LanBridgePayloadHandler = Arc::new(|_| Ok(r#"{"status":"accepted"}"#.to_owned()));
        let handle = runtime
            .start(LanBridgeStartRequest::validated("127.0.0.1", 30).unwrap(), token, handler)
            .unwrap();
        let addr: SocketAddr = handle.status().bind_address.unwrap().parse().unwrap();
        let envelope = seal_lan_bridge_payload(br#"{"kind":"probe"}"#, &[9_u8; LAN_BRIDGE_TOKEN_BYTES], &nonce).unwrap();
        let origin = post(addr, &envelope, "Origin: https://evil.invalid\r\n");
        assert!(origin.starts_with("HTTP/1.1 403 Forbidden"));
        let wrong_key = post(addr, &envelope, "");
        assert!(wrong_key.starts_with("HTTP/1.1 401 Unauthorized"));
        handle.stop().unwrap();
    }

    #[test]
    fn a14_transport_size_header_and_rate_are_bounded() {
        assert_eq!(LAN_BRIDGE_MAX_ATTEMPTS, 8);
        assert!(LAN_BRIDGE_MAX_HEADER_BYTES <= 8 * 1024);
        assert!(LAN_BRIDGE_MAX_HTTP_BODY_BYTES <= 12 * 1024 * 1024);
        assert!(HIGH_PORT_MIN >= 49_152);
    }
}
