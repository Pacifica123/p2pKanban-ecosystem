import {apiRequest,setApiNodeOrigin,setRefreshHandler} from './client';
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
