import { xchacha20poly1305 } from '@noble/ciphers/chacha.js';
import { hmac } from '@noble/hashes/hmac.js';
import { sha256 } from '@noble/hashes/sha2.js';
import { utf8ToBytes } from '@noble/hashes/utils.js';

import {
  ROAMING_PROTOCOL_VERSION,
  type RoamingBoardEvent,
  type RoamingCiphertextRecord,
  type RoamingVersionStamp,
} from './types';

const BOARD_TAG_DOMAIN = utf8ToBytes('p2p-kanban:board-tag:v1');

function bytesToBase64Url(bytes: Uint8Array) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function base64UrlToBytes(value: string) {
  const padding = '='.repeat((4 - (value.length % 4)) % 4);
  const binary = atob(value.replace(/-/g, '+').replace(/_/g, '/') + padding);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

function concat(...parts: Uint8Array[]) {
  const size = parts.reduce((total, part) => total + part.length, 0);
  const output = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

export function decodeBoardKey(value: string) {
  const key = base64UrlToBytes(value);
  if (key.length !== 32) throw new Error('Ключ независимой доски должен содержать 32 байта.');
  return key;
}

export function deriveBoardTag(boardKey: Uint8Array, boardId: string) {
  const digest = hmac(
    sha256,
    boardKey,
    concat(BOARD_TAG_DOMAIN, Uint8Array.of(0), utf8ToBytes(boardId)),
  );
  return bytesToBase64Url(digest);
}

export function sealRoamingEvent(
  event: RoamingBoardEvent,
  boardKey: Uint8Array,
  boardTag: string,
  nonce: Uint8Array,
) {
  if (event.protocolVersion !== ROAMING_PROTOCOL_VERSION) {
    throw new Error('Неподдерживаемая версия журнала доски.');
  }
  if (nonce.length !== 24) throw new Error('XChaCha20 nonce должен содержать 24 байта.');
  const plaintext = utf8ToBytes(JSON.stringify(event));
  const ciphertext = xchacha20poly1305(boardKey, nonce).encrypt(plaintext);
  const record: RoamingCiphertextRecord = {
    version: 1,
    boardTag,
    nonce: bytesToBase64Url(nonce),
    ciphertext: bytesToBase64Url(ciphertext),
  };
  return JSON.stringify(record);
}

export function openRoamingEvent(
  content: string,
  boardKey: Uint8Array,
  expectedBoardTag: string,
) {
  const record = JSON.parse(content) as RoamingCiphertextRecord;
  if (record.version !== 1 || record.boardTag !== expectedBoardTag) {
    throw new Error('Событие относится к другой доске или версии протокола.');
  }
  const nonce = base64UrlToBytes(record.nonce);
  if (nonce.length !== 24) throw new Error('Повреждён nonce события.');
  const plaintext = xchacha20poly1305(boardKey, nonce)
    .decrypt(base64UrlToBytes(record.ciphertext));
  const event = JSON.parse(new TextDecoder().decode(plaintext)) as RoamingBoardEvent;
  if (event.protocolVersion !== ROAMING_PROTOCOL_VERSION) {
    throw new Error('Неподдерживаемая версия события.');
  }
  return event;
}

export function compareVersion(left: RoamingVersionStamp, right: RoamingVersionStamp) {
  if (left.logicalClock !== right.logicalClock) {
    return left.logicalClock < right.logicalClock ? -1 : 1;
  }
  const replicaOrder = left.replicaId.localeCompare(right.replicaId);
  return replicaOrder || left.eventId.localeCompare(right.eventId);
}

export function stampOf(event: RoamingBoardEvent): RoamingVersionStamp {
  return {
    logicalClock: event.logicalClock,
    replicaId: event.replicaId,
    eventId: event.eventId,
  };
}

export const roamingBase64 = {
  encode: bytesToBase64Url,
  decode: base64UrlToBytes,
};
