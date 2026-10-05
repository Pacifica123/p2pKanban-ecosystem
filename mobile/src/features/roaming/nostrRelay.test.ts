import {fetchFromRelays, publishToRelays} from './nostrRelay';
import {finalizeEvent, type Event} from 'nostr-tools/pure';

const key = new Uint8Array(32).fill(1);
const event = (boardTag = 'board') => finalizeEvent({kind:1979,created_at:1,
  tags:[['d',boardTag]],content:'encrypted'},key);
let sockets: FakeSocket[] = [];
let behavior: (socket: FakeSocket, frame: any[]) => void;
class FakeSocket {
  onopen?: () => void;
  onmessage?: (message:{data:string}) => void;
  onerror?: () => void;
  onclose?: () => void;
  constructor(public url:string) { sockets.push(this); queueMicrotask(() => this.onopen?.()); }
  send(raw:string) { behavior(this, JSON.parse(raw)); }
  close() { this.onclose?.(); }
  receive(frame:any[]) { this.onmessage?.({data:JSON.stringify(frame)}); }
}
beforeEach(() => {
  sockets = [];
  globalThis.WebSocket = FakeSocket as unknown as typeof WebSocket;
});
test.each([[[],1],[['r1'],0],[['r1'],2],[['r1','r1'],2]])(
  'an invalid relay quorum cannot acknowledge local work: %j/%s', async (relays, minimum) => {
    await expect(publishToRelays(relays as string[],event(),minimum as number)).rejects.toThrow('Некорректный');
    expect(sockets).toHaveLength(0);
  });
test('one failed relay does not block a valid one-ACK quorum; two ACKs remain pending', async () => {
  behavior=(socket,frame)=> { if (frame[0]==='EVENT') socket.receive(['OK',frame[1].id,socket.url==='r1','offline']); };
  await expect(publishToRelays(['r1','r2'],event(),1)).resolves.toEqual({acceptedRelays:['r1'],failedRelays:['r2']});
  await expect(publishToRelays(['r1','r2'],event(),2)).rejects.toThrow('1 из 2');
});
test('duplicate URL never counts as two independent acknowledgements', async () => {
  behavior=(socket,frame)=>socket.receive(['OK',frame[1].id,true]);
  await expect(publishToRelays(['r1','r1'],event(),1)).resolves.toEqual({acceptedRelays:['r1'],failedRelays:[]});
  expect(sockets).toHaveLength(1);
});
test('a relay cannot inject a valid signed event belonging to a different board', async () => {
  const intended = event(), wrong = event('other');
  behavior=(socket,frame)=> {
    if(frame[0]!=='REQ')return;
    socket.receive(['EVENT',frame[1],wrong]);
    socket.receive(['EVENT',frame[1],intended]);
    socket.receive(['EOSE',frame[1]]);
  };
  await expect(fetchFromRelays({relays:['r1'],kind:1979,boardTag:'board'})).resolves.toEqual({events:[intended],relayCount:1});
});
