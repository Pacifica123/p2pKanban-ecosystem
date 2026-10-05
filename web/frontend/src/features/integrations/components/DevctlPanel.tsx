import { useState } from 'react';
import { apiRequest } from '@/shared/api/client';
import { Button } from '@/shared/ui/Button';
import { TextField, SelectField } from '@/shared/ui/Field';
import { Panel } from '@/shared/ui/Panel';
interface Project {
  projectId: string;
  name: string;
  componentId: string;
  resource: { provider: string; kind: string; locator: string };
  defaultWorkScope: { kind: string; id: string };
}
interface Receipt {
  receiptId: string;
  patchId: string;
  result: string;
  commit: string | null;
  checks: { name: string; status: string }[];
  workItems: { ref: string; transition: string | null }[];
}
interface Preview {
  receipt: Receipt;
  policy: string;
  notice: string;
}
export function DevctlPanel({
  boardId,
  canCreate,
  canImport,
}: {
  boardId: string;
  canCreate: boolean;
  canImport: boolean;
}) {
  const [open, setOpen] = useState(false),
    [projects, setProjects] = useState<Project[]>([]),
    [selected, setSelected] = useState(''),
    [name, setName] = useState(''),
    [locator, setLocator] = useState(''),
    [preview, setPreview] = useState<Preview | null>(null),
    [receipts, setReceipts] = useState<Receipt[]>([]),
    [message, setMessage] = useState(''),
    [busy, setBusy] = useState(false);
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setMessage('');
    try {
      await action();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  async function refresh(id: string) {
    setSelected(id);
    setPreview(null);
    const d = await apiRequest<{ items: { receipt: Receipt }[] }>(
      `/integrations/projects/${id}/receipts`,
    );
    setReceipts(d.items.map((i) => i.receipt));
  }
  return (
    <Panel title="Проект · devctl">
      <Button
        disabled={busy}
        onClick={() =>
          void run(async () => {
            setOpen(!open);
            if (open) return;
            const d = await apiRequest<{ items: Project[] }>(
              `/integrations/projects?boardId=${encodeURIComponent(boardId)}`,
            );
            setProjects(d.items);
            if (d.items[0]) await refresh(d.items[0].projectId);
          })
        }
      >
        {open ? 'Свернуть' : 'Привязки и результаты патчей'}
      </Button>
      {open && (
        <div className="stack">
          <p>
            Свяжите доску с локальным проектом devctl. Импорт сохраняет evidence
            без изменения статусов задач и запуска команд.
          </p>
          {canCreate && (
            <div className="toolbar">
              <TextField
                label="Название проекта"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <TextField
                label="Метка workspace devctl"
                placeholder="kanban-web"
                value={locator}
                onChange={(e) => setLocator(e.target.value)}
              />
              <Button
                disabled={busy || !name.trim() || !locator.trim()}
                onClick={() =>
                  void run(async () => {
                    const p = await apiRequest<Project>(
                      '/integrations/projects',
                      {
                        method: 'POST',
                        body: JSON.stringify({ boardId, name, locator }),
                      },
                    );
                    setProjects((c) => [...c, p]);
                    setName('');
                    setLocator('');
                    await refresh(p.projectId);
                  })
                }
              >
                Создать привязку
              </Button>
            </div>
          )}
          {projects.length > 0 && (
            <>
              <SelectField
                label="Проект"
                value={selected}
                disabled={busy}
                onChange={(e) => {
                  const id = e.target.value;
                  void run(() => refresh(id));
                }}
              >
                {projects.map((p) => (
                  <option key={p.projectId} value={p.projectId}>
                    {p.name} · {p.resource.locator}
                  </option>
                ))}
              </SelectField>
              <Button
                onClick={() => {
                  const p = projects.find((p) => p.projectId === selected);
                  if (!p) return;
                  const f = {
                    schemaVersion: 1,
                    projectId: p.projectId,
                    componentId: p.componentId,
                    resource: p.resource,
                    defaultWorkScope: p.defaultWorkScope,
                  };
                  const url = URL.createObjectURL(
                    new Blob([JSON.stringify(f, null, 2)], {
                      type: 'application/json',
                    }),
                  );
                  const a = document.createElement('a');
                  a.href = url;
                  a.download = 'project.json';
                  a.click();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                }}
              >
                Скачать project.json
              </Button>
              <p className="muted">
                Сохраните в .p2pkanban/project.json проекта. После devctl start
                создайте receipt командой из docs/integrations/devctl-v2.md.
              </p>
              <label className="field">
                Проверить receipt
                <input
                  type="file"
                  accept=".json,application/json"
                  disabled={busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    setPreview(null);
                    if (f)
                      void run(async () => {
                        if (f.size > 256 * 1024)
                          throw new Error('Receipt превышает 256 KiB.');
                        setPreview(
                          await apiRequest<Preview>(
                            `/integrations/projects/${selected}/receipts/preview`,
                            { method: 'POST', body: await f.text() },
                          ),
                        );
                      });
                  }}
                />
              </label>
              {preview && (
                <div className="panel">
                  <strong>
                    {preview.receipt.patchId} · {preview.receipt.result}
                  </strong>
                  <p>Коммит: {preview.receipt.commit || 'нет'}</p>
                  <ul>
                    {preview.receipt.checks.map((c, i) => (
                      <li key={i}>
                        {c.name}: {c.status}
                      </li>
                    ))}
                  </ul>
                  <p>
                    Связанных задач: {preview.receipt.workItems.length}. Это
                    предоставленные пользователем данные, без независимой
                    проверки выполнения.
                  </p>
                  <Button
                    disabled={busy || !canImport}
                    onClick={() =>
                      void run(async () => {
                        const r = await apiRequest<{ duplicate: boolean }>(
                          `/integrations/projects/${selected}/receipts`,
                          {
                            method: 'POST',
                            body: JSON.stringify(preview.receipt),
                          },
                        );
                        await refresh(selected);
                        setMessage(
                          r.duplicate
                            ? 'Receipt уже сохранён.'
                            : 'Evidence сохранено. Статусы задач не изменены.',
                        );
                      })
                    }
                  >
                    Подтвердить импорт evidence
                  </Button>
                </div>
              )}
              <ul>
                {receipts.map((r) => (
                  <li key={r.receiptId}>
                    {r.patchId} · {r.result} · {r.commit?.slice(0, 12)}
                  </li>
                ))}
              </ul>
              <p className="muted">
                Последние 100 receipts. Привязки и evidence хранятся на этом
                узле; roaming их не переносит.
              </p>
            </>
          )}
          {message && <p role="status">{message}</p>}
        </div>
      )}
    </Panel>
  );
}
