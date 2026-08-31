# NALV plugin privacy

Contact: [privacy@nalv.ai](mailto:privacy@nalv.ai)

This plugin sends check content from Dify to NALV. It is not a local-only plugin.

**Connect NALV** uses Google OpenID Connect (`openid` and `email` only) on NALV. NALV receives your Google subject identifier and email so it can create or reuse a personal workspace. The plugin does not request Gmail, Drive, Contacts, or Calendar access. Google credentials never enter this plugin.

## What the plugin sends to NALV

Connect creates a short-lived connect session, then the plugin later exchanges that session server-to-server. The browser never receives a NALV connection key.

When you run a check, the plugin POSTs HTTPS requests to the configured NALV origin. The Marketplace default is `https://app.nalv.ai`. It only calls these NALV surface paths:

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

The plugin does **not** collect billing data and does **not** send Dify workspace API keys.

Customer-support conversations can contain names, order numbers, addresses, or other personal data if those strings appear in the frozen script or the bot's replies. The plugin does not try to detect or strip that content.

## Purpose

NALV uses this content to run a behavior check, store evidence, and return a decision you can inspect.

## What NALV stores

NALV persists workspace-scoped check jobs, evidence, and run artifacts so you can open the Evidence URL later. Surface connection keys are stored as hashes, not as the raw secret. The plugin stores only the scoped, revocable NALV surface token in Dify plugin session storage.

This plugin does not implement a user-facing deletion or retention control. Do not assume a retention period or a delete-on-request workflow until NALV documents and ships one.

## External model providers

NALV evaluation may send check statements and conversation evidence to an external semantic-evaluation provider when that provider is configured on the NALV workspace.

The current production semantic evaluator, when configured, is Google Gemini. In that case, evaluation content may be processed under Google's Gemini / Generative AI terms and privacy policy. If the workspace has no live evaluator, NALV fails closed and does not invent a behavioral PASS.

The plugin itself does not call Gemini, Google, or other model APIs.

## Network destination

The production Marketplace destination is `https://app.nalv.ai`. A private NALV operator may set a different NALV origin in Endpoint settings. The plugin only calls the fixed NALV surface paths on that origin. It does not fetch arbitrary end-user URLs, proxy the web, or crawl.

Request timeout is 120 seconds. Connection keys are redacted from plugin error messages.

## Marketplace risk

Recommended classification: **Medium**. Test prompts, Dify agent replies, conversation or execution metadata, and errors leave Dify for the NALV service.

This is not Low risk. Low risk would require no outbound user or test content.

High risk would apply if a workspace routinely sends health, financial, biometric, children's, or other sensitive personal data through checks. Choose the higher level when that is true for your use.
