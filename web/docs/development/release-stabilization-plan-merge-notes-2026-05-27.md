# Release stabilization plan merge notes 2026-05-27

- Статус: Merge analysis / decision record
- Дата: 2026-05-27
- Назначение: зафиксировать, как объединены два плана стабилизации release/dev lifecycle в канонический документ `release-stabilization-program-v1.md`.

---

## 1. Сравниваемые планы

### План A: free-form strategic response

Сильные стороны:

- четкая north-star модель через Release Confidence Score;
- пороги `diagnostic chaos / partial signal / internal candidate / beta candidate / stable release loop`;
- explicit Unknown Ratio and Reproducibility Index;
- жесткое stop-rule мышление: no fix without failure-mode ID/probe;
- сильная связь с текущим состоянием продукта: core CRUD, appearance and activity ready; auth/labels/checklists/comments not yet release-proof;
- отдельная трактовка `PUSH_FAILED` как transport-only failure;
- акцент на двух последовательных прогонах and repeatability.

Слабые стороны:

- меньше формальной детализации supported reality;
- меньше artifact-contract деталей;
- меньше ledger implementation detail;
- workstreams были намечены, но не настолько строго разделены.

### План B: unapplied `deep-release-autopsy-strategy` patch

Сильные стороны:

- широкий `Supported reality v1`;
- три ledger-а: Problem, Probe, Decision;
- подробная failure taxonomy;
- большой artifact/redaction/archive contract;
- сильные workstreams по DB/runtime/Windows/config/migrations/smoke/browser/devctl;
- phased roadmap and strategic patch chain;
- initial known failure-mode seed list.

Слабые стороны:

- Release Confidence Score был менее строгим и менее управленческим;
- меньше акцента на score thresholds;
- меньше явной привязки к текущему product-ready/future-ready surface;
- риск, что большой стратегический документ останется отдельно от acceptance thresholds;
- `deep-release-autopsy-strategic-plan-v1.md` как имя хорошо описывает подход, но хуже работает как canonical program name для дальнейших патчей.

---

## 2. Сходства

Оба плана сходятся в ключевых принципах:

1. сначала evidence, потом fix;
2. каждый сбой должен иметь failure-mode ID;
3. release-gates должны производить bundle, а не только console output;
4. skipped/not implemented нельзя считать pass;
5. DB/runtime/frontend/browser/Windows должны проверяться как отдельные failure surfaces;
6. managed DB and managed runtime are required for real release confidence;
7. smoke must be repeatable and idempotent;
8. devctl push failure must not be confused with patch/content failure;
9. artifacts must be shareable, redacted and small;
10. stabilization should become a thematic patch chain, not one giant blind patch.

---

## 3. Различия

| Area | План A | План B | Итоговое решение |
|---|---|---|---|
| North-star | 100-point Release Confidence Score | Several north-star metrics | Keep score + keep supporting metrics |
| Supported reality | summarized | detailed | Keep detailed reality from B |
| Ledgers | Problem Ledger primary | Problem/Probe/Decision Ledgers | Keep three ledgers |
| Product grounding | explicit | weaker | Keep explicit product-ready/future-ready split |
| Artifact contract | practical bundle | detailed bundle/redaction/archive | Keep detailed contract + score impact |
| Roadmap | 11-step patch chain | 12-step patch chain | Merge into 13-step chain |
| Failure taxonomy | concise families | detailed families/statuses | Keep detailed taxonomy + add score classes |
| Smoke | fresh/dirty distinction | fresh/dirty + idempotency | Keep both, require two-run repeatability |
| Browser | real backend vs mocked emphasized | browser gate hardening | Keep both and score only real-backend path |
| Devctl/VCS | strong transport-only separation | REL-VCS seed | Keep as mandatory workstream |
| Risk control | stop-rule and decision questions | risk register | Keep both review questions and risk register |

---

## 4. Метастратегия объединения

Не использовать ни один план как единственный источник истины.

Итоговая схема:

```text
Manifesto -> why and philosophy
Release Stabilization Program -> canonical execution model
Ledgers -> durable memory
Autopsy/release-gates bundle -> evidence production
Patch chain -> incremental capability rollout
Release Confidence Score -> release decision
```

Правило объединения:

```text
Если элемент дает coverage -> включить.
Если элемент дает governance -> включить.
Если элемент дублирует другой без новой силы -> свернуть.
Если элемент повышает риск unsafe automation -> отложить за consent/profile boundary.
Если элемент делает future-ready surface похожим на готовый release path -> понизить до known limitation.
```

---

## 5. Что взято из плана A

- Release Confidence Score 0-100.
- Score classes and thresholds.
- Unknown Ratio.
- Reproducibility Index.
- Failure Classification Coverage.
- Remediation Closure Rate.
- Product-path grounding.
- Fresh vs dirty smoke as release signal.
- Real backend browser path as separate release confidence input.
- Devctl transport-only classification.
- Seven review questions for every future patch.

---

## 6. Что взято из плана B

- Supported reality v1.
- OS/shell/toolchain/runtime/database/verification contexts.
- Problem/Probe/Decision Ledger model.
- Failure taxonomy families.
- Artifact system and redaction/archive contracts.
- Workstreams WS-1..WS-12.
- Phased roadmap.
- Initial known failure-mode seed list.
- Risk register.
- Strategic patch chain.

---

## 7. Что отброшено или ослаблено

- Простая склейка двух длинных документов.
- Идея, что сам большой документ уже является прогрессом без score/acceptance checks.
- Рискованный ранний rollout controlled mutators without read-only diagnostics.
- Any implied green status for `not_implemented` gates.
- Any release path that treats mocked browser smoke as real backend proof.
- Any default-state smoke assumption on dirty shared dev DB.
- Any interpretation of remote push failure as patch failure.

---

## 8. Дополнительные слабые места, найденные после объединения

### 8.1. Score gaming

Риск: команда может набрать высокий score за счет легких gates, оставив тяжелые unknowns.

Решение: score должен ссылаться на required evidence, а unknown blockers force-cap score ниже beta threshold.

### 8.2. Ledger bloat

Риск: Problem Ledger станет кладбищем старых записей.

Решение: statuses, severity filters, stale review date, accepted_non_blocking state.

### 8.3. Over-automation before trust

Риск: bootstrapper начнет делать слишком много и потеряет доверие.

Решение: diagnostic profile first, controlled mutators later, consent summaries always.

### 8.4. Product/release boundary blur

Риск: stabilization patches начнут незаметно добавлять product features.

Решение: future patches must state whether they affect product code, release infra, docs, or all three.

### 8.5. Human handoff gap

Риск: bundle будет machine-readable, но пользователю все равно непонятно, что делать.

Решение: `next-actions.md`, `rerun-commands.md`, `manual-remediation-pack.md` are required artifacts.

### 8.6. False clean-machine confidence

Риск: clean-machine dry gate passes, but real runtime still fails.

Решение: split clean-machine dry/deps/runtime profiles and score them separately.

### 8.7. Security drift in diagnostic tooling

Риск: more diagnostics means more sensitive data exposure.

Решение: redaction report, env allowlist, connection-string masking, archive secret scan.

---

## 9. Final decision

Каноническим документом становится:

```text
docs/development/release-stabilization-program-v1.md
```

Он не заменяет манифест, а превращает его в исполнимую программу.

Unapplied external patch with `deep-release-autopsy-strategic-plan-v1.md` не нужно применять separately: его полезные идеи включены в канонический program document, а имя документа заменено на более операционное и устойчивое для будущей patch-chain.
