import json
import os
import re
import sys
import urllib.error
import urllib.request
import http.cookiejar
import uuid
from datetime import datetime, timezone

BASE_URL = os.environ.get('BASE_URL', 'http://127.0.0.1:18080/api/v1').rstrip('/')
TIMEOUT = float(os.environ.get('TIMEOUT', '10'))


def default_smoke_user_email() -> str:
    explicit_email = os.environ.get('SMOKE_USER_EMAIL')
    if explicit_email:
        return explicit_email
    run_id = os.environ.get('SMOKE_RUN_ID') or os.environ.get('DEVBOOTSTRAP_RUN_ID')
    if run_id:
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', run_id).strip('-').lower()[:48]
        if slug:
            return f'smoke-user-{slug}@local.test'
    return 'smoke-user@local.test'


SMOKE_USER_EMAIL = default_smoke_user_email()
SMOKE_USER_PASSWORD = os.environ.get('SMOKE_USER_PASSWORD', 'SmokePass123!')
SMOKE_USER_DISPLAY_NAME = os.environ.get('SMOKE_USER_DISPLAY_NAME', 'Smoke Test User')

COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIE_JAR))
ACCESS_TOKEN = None


def parse_payload(raw: str):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def request(
    method: str,
    path: str,
    body=None,
    expected_status: int = 200,
    include_auth: bool = True,
    auth_token=None,
    extra_headers=None,
):
    global ACCESS_TOKEN
    url = f"{BASE_URL}{path}"
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')

    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('Content-Type', 'application/json')
    token = ACCESS_TOKEN if auth_token is None else auth_token
    if include_auth and token:
        req.add_header('Authorization', f'Bearer {token}')
    for key, value in (extra_headers or {}).items():
        req.add_header(key, value)

    status = None
    payload = None
    try:
        with OPENER.open(req, timeout=TIMEOUT) as resp:
            status = resp.status
            payload = parse_payload(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        status = e.code
        payload = parse_payload(e.read().decode('utf-8', errors='replace'))
    except Exception as e:
        print(f"[FAIL] {method} {path} -> {e}")
        raise

    if status != expected_status:
        print(f"[FAIL] {method} {path} -> expected {expected_status}, got {status}\n{json.dumps(payload, ensure_ascii=False, indent=2)}")
        raise RuntimeError(f"Unexpected status for {method} {path}: expected {expected_status}, got {status}")

    suffix = "" if status < 400 else " (expected error)"
    print(f"[OK] {method} {path} -> {status}{suffix}")
    return status, payload


def api_data(payload):
    if isinstance(payload, dict) and 'data' in payload:
        return payload['data']
    return payload


def data_id(payload):
    data = api_data(payload)
    if isinstance(data, dict) and 'id' in data:
        return data['id']
    raise RuntimeError(f'Could not extract id from payload: {payload}')


def assert_equal(actual, expected, label: str):
    if actual != expected:
        raise RuntimeError(f"Assertion failed for {label}: expected {expected!r}, got {actual!r}")
    print(f"[ASSERT] {label} == {expected!r}")


def assert_true(value, label: str):
    if value is not True:
        raise RuntimeError(f"Assertion failed for {label}: expected True, got {value!r}")
    print(f"[ASSERT] {label} is True")


def assert_in(member, container, label: str):
    if member not in container:
        raise RuntimeError(f"Assertion failed for {label}: expected {member!r} in {container!r}")
    print(f"[ASSERT] {member!r} in {label}")


def assert_error(payload, code: str, message_substring: str, label: str):
    error = payload.get('error') if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise RuntimeError(f"Assertion failed for {label}: expected error payload, got {payload!r}")
    assert_equal(error.get('code'), code, f"{label}.code")
    message = error.get('message', '')
    if message_substring not in message:
        raise RuntimeError(
            f"Assertion failed for {label}.message: expected substring {message_substring!r}, got {message!r}"
        )
    print(f"[ASSERT] {label}.message contains {message_substring!r}")


def ensure_smoke_session():
    global ACCESS_TOKEN
    sign_up_payload = {
        'email': SMOKE_USER_EMAIL,
        'password': SMOKE_USER_PASSWORD,
        'displayName': SMOKE_USER_DISPLAY_NAME,
    }
    status, payload = request('POST', '/auth/sign-up', sign_up_payload, expected_status=201, include_auth=False)
    data = api_data(payload)
    if status == 201:
        ACCESS_TOKEN = data['accessToken']
        return data


def ensure_smoke_session_fallback_sign_in():
    global ACCESS_TOKEN
    _, payload = request('POST', '/auth/sign-in', {
        'email': SMOKE_USER_EMAIL,
        'password': SMOKE_USER_PASSWORD,
    }, expected_status=200, include_auth=False)
    data = api_data(payload)
    ACCESS_TOKEN = data['accessToken']
    return data


def ensure_authenticated_user():
    try:
        return ensure_smoke_session()
    except RuntimeError:
        return ensure_smoke_session_fallback_sign_in()


def sign_up_ephemeral_user(email_suffix: str):
    global ACCESS_TOKEN
    _, payload = request('POST', '/auth/sign-up', {
        'email': f'smoke-other-{email_suffix}@local.test',
        'password': SMOKE_USER_PASSWORD,
        'displayName': 'Smoke Other User',
    }, expected_status=201, include_auth=False)
    data = api_data(payload)
    ACCESS_TOKEN = data['accessToken']
    return data


def main():
    global ACCESS_TOKEN
    print(f"BASE_URL={BASE_URL}")
    print(f"SMOKE_USER_EMAIL={SMOKE_USER_EMAIL}")

    created = {
        'workspace_id': None,
        'board_id': None,
        'column_id': None,
        'card_id': None,
        'second_card_id': None,
        'label_id': None,
        'checklist_id': None,
        'checklist_item_id': None,
        'comment_id': None,
    }

    try:
        request('GET', '/health', include_auth=False)
        _, anonymous_workspaces_payload = request('GET', '/workspaces', expected_status=401, include_auth=False)
        assert_error(anonymous_workspaces_payload, 'unauthorized', 'Authentication is required', 'anonymous workspaces blocked')
        _, wrong_token_payload = request('GET', '/workspaces', expected_status=401, include_auth=True, auth_token='not-a-valid-token')
        assert_error(wrong_token_payload, 'unauthorized', 'Access token', 'wrong bearer token blocked')

        ensure_authenticated_user()
        _, session_payload = request('GET', '/auth/session')
        session_data = api_data(session_payload)
        assert_true(session_data['authenticated'], 'session authenticated')
        assert_equal(session_data['user']['email'], SMOKE_USER_EMAIL.lower(), 'session user email')

        _, ws = request('POST', '/workspaces', {
            'name': 'Smoke Workspace',
            'visibility': 'private',
        }, expected_status=201)
        created['workspace_id'] = data_id(ws)

        request('GET', '/workspaces')

        _, board = request('POST', f"/workspaces/{created['workspace_id']}/boards", {
            'name': 'Smoke Board',
            'boardType': 'kanban',
        }, expected_status=201)
        created['board_id'] = data_id(board)

        _, column = request('POST', f"/boards/{created['board_id']}/columns", {
            'name': 'Todo',
        }, expected_status=201)
        created['column_id'] = data_id(column)

        request('GET', f"/boards/{created['board_id']}/columns")

        _, card = request('POST', f"/boards/{created['board_id']}/cards", {
            'title': 'First smoke card',
            'columnId': created['column_id'],
        }, expected_status=201)
        created['card_id'] = data_id(card)

        _, second_card = request('POST', f"/boards/{created['board_id']}/cards", {
            'title': 'Second smoke card',
            'columnId': created['column_id'],
        }, expected_status=201)
        created['second_card_id'] = data_id(second_card)

        primary_access_token = ACCESS_TOKEN
        other_session = sign_up_ephemeral_user(created['workspace_id'])
        other_access_token = other_session['accessToken']
        _, forbidden_workspace = request('GET', f"/workspaces/{created['workspace_id']}", expected_status=403, auth_token=other_access_token)
        assert_error(forbidden_workspace, 'forbidden', 'Workspace is not accessible', 'foreign workspace blocked')
        _, forbidden_activity = request('GET', f"/boards/{created['board_id']}/activity", expected_status=403, auth_token=other_access_token)
        assert_error(forbidden_activity, 'forbidden', 'Workspace is not accessible', 'foreign board activity blocked')
        _, forbidden_audit = request('GET', f"/workspaces/{created['workspace_id']}/audit-log", expected_status=403, auth_token=other_access_token)
        assert_error(forbidden_audit, 'forbidden', 'Workspace is not accessible', 'foreign audit log blocked')
        _, forbidden_export = request('POST', '/integrations/import-export/exports', {
            'scopeKind': 'board',
            'workspaceId': created['workspace_id'],
            'boardId': created['board_id'],
            'exportMode': 'backup_snapshot',
        }, expected_status=403, auth_token=other_access_token)
        assert_error(forbidden_export, 'forbidden', 'Workspace is not accessible', 'foreign export blocked')

        _, other_replica_payload = request('POST', '/sync/replicas', {
            'replicaKey': f"smoke-foreign-replica-{created['workspace_id']}",
            'kind': 'browser_profile',
            'displayName': 'Smoke foreign replica',
            'protocolVersion': 'sync-baseline-v1',
        }, expected_status=201, auth_token=other_access_token)
        other_replica = api_data(other_replica_payload)['replica']
        _, forbidden_sync_pull = request('GET', f"/sync/pull?replicaId={other_replica['id']}&scope=workspace&workspaceId={created['workspace_id']}&lastServerOrder=0&limit=5", expected_status=403, auth_token=other_access_token)
        assert_error(forbidden_sync_pull, 'forbidden', 'Workspace is not accessible', 'foreign sync pull blocked')
        _, forbidden_sync_push = request('POST', '/sync/push', {
            'replicaId': other_replica['id'],
            'workspaceId': created['workspace_id'],
            'events': [{
                'eventId': str(uuid.uuid4()),
                'replicaId': other_replica['id'],
                'replicaSeq': 1,
                'entityType': 'card',
                'entityId': created['card_id'],
                'operation': 'update',
                'fieldMask': ['title'],
                'logicalClock': 1,
                'payload': {'title': 'Forbidden write'},
            }],
        }, expected_status=403, auth_token=other_access_token)
        assert_error(forbidden_sync_push, 'forbidden', 'Workspace is not accessible', 'foreign sync push blocked')
        ACCESS_TOKEN = primary_access_token

        request('GET', f"/cards/{created['card_id']}")
        request('PATCH', f"/cards/{created['card_id']}", {
            'title': 'Renamed smoke card',
            'priority': 'high',
        })
        request('POST', f"/cards/{created['card_id']}/move", {
            'targetColumnId': created['column_id'],
            'position': 2048.0,
        })
        _, reorder_payload = request('POST', f"/columns/{created['column_id']}/cards/reorder", {
            'items': [
                {'cardId': created['second_card_id'], 'position': 1024.0},
                {'cardId': created['card_id'], 'position': 2048.0},
            ],
        })
        reordered_cards = api_data(reorder_payload)['items']
        assert_equal(reordered_cards[0]['id'], created['second_card_id'], 'reorder first card')
        assert_equal(reordered_cards[1]['id'], created['card_id'], 'reorder second card')
        request('POST', f"/cards/{created['card_id']}/archive")
        request('POST', f"/cards/{created['card_id']}/unarchive")
        request('GET', f"/boards/{created['board_id']}/cards")

        _, label_payload = request('POST', f"/boards/{created['board_id']}/labels", {
            'name': 'Smoke Label',
            'color': '#60a5fa',
        }, expected_status=201)
        created['label_id'] = data_id(label_payload)
        _, labels_payload = request('GET', f"/boards/{created['board_id']}/labels")
        labels = api_data(labels_payload)['items']
        assert_true(any(item['id'] == created['label_id'] for item in labels), 'created label visible in board labels')
        _, labeled_card_payload = request('PUT', f"/cards/{created['card_id']}/labels", {
            'labelIds': [created['label_id']],
        })
        assert_in(created['label_id'], api_data(labeled_card_payload)['labelIds'], 'card label ids after attach')
        _, unlabeled_card_payload = request('PUT', f"/cards/{created['card_id']}/labels", {
            'labelIds': [],
        })
        assert_equal(api_data(unlabeled_card_payload)['labelIds'], [], 'card label ids after detach')
        _, renamed_label_payload = request('PATCH', f"/labels/{created['label_id']}", {
            'name': 'Renamed Smoke Label',
        })
        assert_equal(api_data(renamed_label_payload)['name'], 'Renamed Smoke Label', 'label rename')
        request('DELETE', f"/labels/{created['label_id']}")

        _, checklist_payload = request('POST', f"/cards/{created['card_id']}/checklists", {
            'title': 'Smoke Checklist',
        }, expected_status=201)
        created['checklist_id'] = data_id(checklist_payload)
        _, checklists_payload = request('GET', f"/cards/{created['card_id']}/checklists")
        checklists = api_data(checklists_payload)['items']
        assert_true(any(item['id'] == created['checklist_id'] for item in checklists), 'created checklist visible on card')
        _, item_payload = request('POST', f"/checklists/{created['checklist_id']}/items", {
            'title': 'Smoke item',
        }, expected_status=201)
        created['checklist_item_id'] = data_id(item_payload)
        _, done_item_payload = request('PATCH', f"/checklist-items/{created['checklist_item_id']}", {
            'isDone': True,
        })
        assert_true(api_data(done_item_payload)['isDone'], 'checklist item done')
        _, reopened_item_payload = request('PATCH', f"/checklist-items/{created['checklist_item_id']}", {
            'isDone': False,
        })
        assert_equal(api_data(reopened_item_payload)['isDone'], False, 'checklist item reopened')
        request('DELETE', f"/checklist-items/{created['checklist_item_id']}")
        request('DELETE', f"/checklists/{created['checklist_id']}")

        _, comment_payload = request('POST', f"/cards/{created['card_id']}/comments", {
            'body': 'Smoke comment',
        }, expected_status=201)
        created['comment_id'] = data_id(comment_payload)
        _, comments_payload = request('GET', f"/cards/{created['card_id']}/comments")
        comments = api_data(comments_payload)['items']
        assert_true(any(item['id'] == created['comment_id'] for item in comments), 'created comment visible on card')
        _, updated_comment_payload = request('PATCH', f"/comments/{created['comment_id']}", {
            'body': 'Updated smoke comment',
        })
        assert_equal(api_data(updated_comment_payload)['body'], 'Updated smoke comment', 'comment update')
        request('DELETE', f"/comments/{created['comment_id']}")

        _, archived_board_payload = request('POST', f"/boards/{created['board_id']}/archive")
        assert_true(api_data(archived_board_payload)['isArchived'], 'board archived')

        _, archived_workspace_payload = request('POST', f"/workspaces/{created['workspace_id']}/archive")
        assert_true(api_data(archived_workspace_payload)['isArchived'], 'workspace archived')

        _, board_activity_payload = request('GET', f"/boards/{created['board_id']}/activity")
        board_activity = api_data(board_activity_payload)
        assert_true(len(board_activity['items']) >= 4, 'board activity has several entries')

        _, card_activity_payload = request('GET', f"/cards/{created['card_id']}/activity")
        card_activity = api_data(card_activity_payload)
        assert_true(len(card_activity['items']) >= 4, 'card activity has several entries')

        _, audit_payload = request('GET', f"/workspaces/{created['workspace_id']}/audit-log")
        audit_items = api_data(audit_payload)['items']
        assert_true(len(audit_items) >= 3, 'workspace audit has several entries')

        _, export_payload = request('POST', '/integrations/import-export/exports', {
            'scopeKind': 'board',
            'workspaceId': created['workspace_id'],
            'boardId': created['board_id'],
            'exportMode': 'backup_snapshot',
            'includeArchived': True,
            'includeActivityHistory': True,
            'includeAppearance': True,
        }, expected_status=202)
        export_data = api_data(export_payload)
        assert_equal(export_data['status'], 'ready', 'portable export status')
        bundle = export_data['bundle']
        manifest = bundle['manifest.json']
        assert_equal(manifest['format'], 'p2p_planner_bundle', 'export manifest format')
        assert_equal(manifest['formatVersion'], 1, 'export manifest format version')
        assert_equal(manifest['summary']['entityCounts']['boards'], 1, 'export board count')
        assert_true(manifest['summary']['entityCounts']['cards'] >= 2, 'export card count')
        assert_true(len(bundle['payload']['cards']) >= 2, 'export payload includes cards')
        assert_true('user_sessions' not in json.dumps(bundle), 'export bundle excludes raw session table')

        _, preview_payload = request('POST', '/integrations/import-export/imports/preview', {
            'importMode': 'restore_backup',
            'restoreStrategy': 'create_copy',
            'bundle': bundle,
        })
        preview_data = api_data(preview_payload)
        assert_equal(preview_data['status'], 'preview_ready', 'import preview status')
        assert_equal(preview_data['detectedFormat'], 'p2p_planner_bundle', 'import preview detected format')
        assert_equal(preview_data['summary']['entityCounts']['boards'], 1, 'import preview board count')

        _, replica_payload = request('POST', '/sync/replicas', {
            'replicaKey': f"smoke-replica-{created['workspace_id']}",
            'kind': 'browser_profile',
            'displayName': 'Smoke browser replica',
            'protocolVersion': 'sync-baseline-v1',
        }, expected_status=201)
        replica = api_data(replica_payload)['replica']
        assert_equal(replica['status'], 'active', 'sync replica active')
        _, replicas_payload = request('GET', '/sync/replicas')
        replicas = api_data(replicas_payload)['items']
        assert_true(any(item['id'] == replica['id'] for item in replicas), 'registered replica visible')
        _, sync_status_payload = request('GET', f"/sync/status?replicaId={replica['id']}")
        sync_status = api_data(sync_status_payload)
        assert_true(sync_status['healthy'], 'sync status healthy')

        sync_event = {
            'eventId': str(uuid.uuid4()),
            'replicaId': replica['id'],
            'replicaSeq': 1,
            'entityType': 'card',
            'entityId': created['card_id'],
            'operation': 'update',
            'fieldMask': ['title'],
            'logicalClock': 1,
            'occurredAt': datetime.now(timezone.utc).isoformat(),
            'payload': {'title': 'Renamed smoke card'},
            'metadata': {'source': 'smoke_core_api'},
        }
        _, push_payload = request('POST', '/sync/push', {
            'replicaId': replica['id'],
            'workspaceId': created['workspace_id'],
            'events': [sync_event],
        })
        push_result = api_data(push_payload)['results'][0]
        assert_equal(push_result['status'], 'accepted', 'sync push first status')
        assert_true(push_result['serverOrder'] >= 1, 'sync push server order assigned')
        _, duplicate_push_payload = request('POST', '/sync/push', {
            'replicaId': replica['id'],
            'workspaceId': created['workspace_id'],
            'events': [sync_event],
        })
        duplicate_result = api_data(duplicate_push_payload)['results'][0]
        assert_equal(duplicate_result['status'], 'duplicate', 'sync duplicate push status')
        assert_equal(duplicate_result['serverOrder'], push_result['serverOrder'], 'sync duplicate server order stable')
        _, pull_payload = request('GET', f"/sync/pull?replicaId={replica['id']}&scope=workspace&workspaceId={created['workspace_id']}&lastServerOrder=0&limit=20")
        pulled = api_data(pull_payload)
        assert_true(any(item['eventId'] == sync_event['eventId'] for item in pulled['events']), 'sync pull includes pushed event')

        _, me_payload = request('GET', '/me')
        me = api_data(me_payload)
        assert_equal(me['email'], SMOKE_USER_EMAIL.lower(), 'me email')

        _, devices_payload = request('GET', '/me/devices')
        devices = api_data(devices_payload)
        assert_true(len(devices) >= 1, 'at least one device registered')

        _, sign_out_all_payload = request('POST', '/auth/sign-out-all')
        sign_out_all_data = api_data(sign_out_all_payload)
        assert_true(sign_out_all_data['signedOut'], 'sign out all result')
        ACCESS_TOKEN = None

        _, unauthorized_workspaces = request('GET', '/workspaces', expected_status=401, include_auth=False)
        assert_error(unauthorized_workspaces, 'unauthorized', 'Authentication is required', 'anonymous workspaces blocked')

        ensure_smoke_session_fallback_sign_in()
        request('GET', '/workspaces')

        print('[DONE] smoke_core_api.py finished successfully')
    except Exception as e:
        print(f"\n[SMOKE FAILED] {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
