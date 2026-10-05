import React from 'react';
import {AuthProvider,useAuth} from './AuthProvider';
import {ApiError} from '../../shared/api/client';
import {clearSessionBoundStorage,loadStoredSession} from '../../shared/storage/storage';
import {nativeRefresh} from '../../shared/api/endpoints';
const {act,create} = require('react-test-renderer');
const mockClient={clear:jest.fn()};
jest.mock('@tanstack/react-query',()=>({useQueryClient:()=>mockClient}));
jest.mock('../../app/NetworkProvider',()=>({useNetwork:()=>({isOnline:true})}));
jest.mock('../connection/ConnectionProvider',()=>({useConnection:()=>({nodeOrigin:'http://pc'})}));
jest.mock('../reminders/service',()=>({cancelAllCardReminders:jest.fn(async()=>{})}));
jest.mock('../../shared/storage/storage',()=>({clearSessionBoundStorage:jest.fn(),loadStoredSession:jest.fn(),saveStoredSession:jest.fn()}));
jest.mock('../../shared/api/endpoints',()=>({nativeRefresh:jest.fn()}));
test.each([401,403])('HTTP refresh %s preserves authenticated local replica and queue',async status=>{
  jest.clearAllMocks();
  (loadStoredSession as jest.Mock).mockResolvedValue({nodeOrigin:'http://pc',user:{id:'owner'},accessToken:'expired',refreshToken:'expired',accessTokenExpiresAt:'0'});
  (nativeRefresh as jest.Mock).mockRejectedValue(new ApiError('expired',{status}));
  let state:ReturnType<typeof useAuth>|undefined;
  function Probe(){state=useAuth();return null;}
  let renderer:any;
  await act(async()=>{renderer=create(<AuthProvider><Probe/></AuthProvider>);});
  expect(nativeRefresh).toHaveBeenCalled();
  expect(state?.status).toBe('authenticated');
  expect(state?.user?.id).toBe('owner');
  expect(state?.isOfflineSession).toBe(true);
  expect(clearSessionBoundStorage).not.toHaveBeenCalled();
  expect(mockClient.clear).not.toHaveBeenCalled();
  await act(async()=>renderer.unmount());
});
