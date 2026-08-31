# NALV plugin privacy

Contact: [privacy@nalv.ai](mailto:privacy@nalv.ai)

This plugin sends check content from Dify to NALV. It is not a local-only plugin.

**Connect NALV** uses Google OpenID Connect (`openid` and `email` only) on NALV. NALV receives your Google subject identifier and email so it can create or reuse a personal workspace. The plugin does not request Gmail, Drive, Contacts, or Calendar access. Google credentials never enter this plugin.

## What the plugin sends to NALV

Connect creates a short-lived connect session, then the plugin later exchanges that session server-to-server. The browser never receives a NALV connection key.

When you run a check, the plugin POSTs HTTPS requests to `https://app.nalv.ai`. The destination is fixed in the plugin and is not configurable. It only calls these NALV surface paths:

- `/api/preflight/surface/connect/sessions`
- `/api/preflight/surface/connect/sessions/{id}/exchange`
- `/api/preflight/surface/connect/disconnect`
- `/api/preflight/surface/dify/bind`
- `/api/preflight/surface/jobs`
- `/api/preflight/surface/jobs/{jobId}/evidence`

Those requests may include:

- The scoped NALV surface token, as an `Authorization: Bearer` header
- The selected Dify `app_id` and app mode
- Frozen customer-turn text issued by NALV for the check
- Observed assistant replies from the selected Chatbot or Chatflow
- The Dify conversation id for that check
- NALV job and execution identifiers
- An adapter/infrastructure error code and message text when a Dify reverse invocation fails

Adapter runtime metadata (turn-level invocation details) stays in Dify; it is removed before the evidence request is sent.

The plugin does **not** collect billing data and does **not** send Dify workspace API keys.

Customer-support conversations can contain names, order numbers, addresses, or other personal data if those strings appear in the frozen script or the bot's replies. The plugin does not try to detect or strip that content.

## Purpose

NALV uses this content to run a behavior check, store evidence, and return a decision you can inspect.

## What NALV stores

NALV persists workspace-scoped check jobs, evidence, and run artifacts so you can open the Evidence URL later. NALV stores persisted surface connection credentials only as hashes, not as raw secrets.

## Credential storage

Where each credential lives:

- **NALV server-side**: persisted surface connection credentials are stored as hashes, not as raw secrets.
- **Dify plugin storage**: after Connect, the scoped NALV surface token is stored in Dify plugin storage so it can be presented as a Bearer credential. Disconnect deletes it locally and asks NALV to revoke it. During Connect, a pending exchange secret is temporarily stored and deleted after a successful exchange or a terminal expiry/error state.
- **Dify endpoint settings**: an optional manual NALV connection key may be stored as a Dify-managed secret setting.
- **Request fallback**: when neither connected storage nor the endpoint setting supplies a credential, an advanced request may provide a `surface_token` in its payload. A payload-supplied token is used only for that request and is never persisted by the plugin.

Dify plugin storage is provided by the Dify platform; this plugin makes no claim that it is encrypted.

This plugin does not implement a user-facing deletion or retention control. Do not assume a retention period or a delete-on-request workflow until NALV documents and ships one.

## External model providers

NALV evaluation may send check statements and conversation evidence to an external semantic-evaluation provider when that provider is configured on the NALV workspace.

The current production semantic evaluator, when configured, is Google Gemini. In that case, evaluation content may be processed under Google's Gemini / Generative AI terms and privacy policy. If the workspace has no live evaluator, NALV fails closed and does not invent a behavioral PASS.

The plugin itself does not call Gemini, Google, or other model APIs.

## Network destination

The production Marketplace destination is `https://app.nalv.ai`, fixed in the plugin. It is not configurable, and request payloads cannot redirect it. The plugin does not fetch arbitrary end-user URLs, proxy the web, or crawl.

Request timeout is 120 seconds. Connection keys are redacted from plugin error messages.

## Marketplace risk

Recommended classification: **High**. Current Dify Marketplace requirements classify handling of authentication data as High risk, and this plugin handles authentication data: the scoped, revocable NALV surface token used as a Bearer credential, and the short-lived Connect exchange secret.

In addition, test prompts, Dify agent replies, conversation or execution metadata, and errors leave Dify for the NALV service. This is not Low risk; Low risk would require no outbound user or test content.
