import {apiRequest,inFlightRequests,setApiNodeOrigin,setRefreshHandler} from './client';
beforeEach(()=>{jest.useFakeTimers();setApiNodeOrigin('http://peer');setRefreshHandler(null);});
afterEach(()=>jest.useRealTimers());
function canceledFetch(){
  globalThis.fetch=jest.fn((_url,init)=>new Promise((_resolve,reject)=>{
    init?.signal?.addEventListener('abort',()=>reject(new TypeError('fetch request has been canceled')));
  })) as typeof fetch;
}
test('RN cancellation at the request deadline is TIMEOUT',async()=>{
  canceledFetch(); const result=apiRequest('/test',{}, {timeoutMs:10});
  const assertion=expect(result).rejects.toMatchObject({code:'TIMEOUT'});
  await jest.advanceTimersByTimeAsync(10);await assertion;
});
test('caller abort is CANCELED',async()=>{
  canceledFetch();const controller=new AbortController();
  const assertion=expect(apiRequest('/test',{signal:controller.signal})).rejects.toMatchObject({code:'CANCELED'});
  controller.abort();await assertion;
});
test('body read has a deadline and a subsequent request recovers',async()=>{
  globalThis.fetch=jest.fn(async (_url,init)=>({ok:true,status:200,text:()=>new Promise((_resolve,reject)=>{
    init?.signal?.addEventListener('abort',()=>reject(new TypeError('fetch request has been canceled')));
  })})) as unknown as typeof fetch;
  const assertion=expect(apiRequest('/test',{}, {timeoutMs:10})).rejects.toMatchObject({code:'TIMEOUT'});
  await jest.advanceTimersByTimeAsync(10);await assertion;
  globalThis.fetch=jest.fn(async()=>({ok:true,status:200,text:async()=>'{"data":"ok"}'})) as unknown as typeof fetch;
  expect(await apiRequest('/test')).toBe('ok');
});
test('a node that did not answer is not asked again during the cool-down',async()=>{
  canceledFetch(); const first=apiRequest('/test',{}, {timeoutMs:10});
  const assertion=expect(first).rejects.toMatchObject({code:'TIMEOUT'});
  await jest.advanceTimersByTimeAsync(10);await assertion;
  const calls=(globalThis.fetch as jest.Mock).mock.calls.length;
  await expect(apiRequest('/test')).rejects.toMatchObject({code:'NODE_UNREACHABLE',status:0});
  expect((globalThis.fetch as jest.Mock).mock.calls.length).toBe(calls);
  expect(inFlightRequests()).toEqual([]);
});
test('in-flight requests are visible to the stall watch until they settle',async()=>{
  canceledFetch(); const pending=apiRequest('/boards/x',{method:'PUT'}, {timeoutMs:50});
  const assertion=expect(pending).rejects.toMatchObject({code:'TIMEOUT'});
  await jest.advanceTimersByTimeAsync(20);
  expect(inFlightRequests()).toEqual([expect.objectContaining({method:'PUT',path:'/api/v1/boards/x'})]);
  await jest.advanceTimersByTimeAsync(30);await assertion;
  expect(inFlightRequests()).toEqual([]);
});
