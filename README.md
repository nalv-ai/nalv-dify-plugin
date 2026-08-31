# NALV for Dify

NALV verifies customer-support bot behavior.

The loop is:

Change something → Run a Check → inspect Evidence → fix behavior → Check again.

This plugin is not observability, chatbot scoring, a red-team toolkit, a Dify agent builder, or a generic LLM-as-judge product.

## What this plugin does

The plugin connects a Dify Chatbot or Chatflow to a NALV workspace.

When you run a check, it:

1. Asks NALV for the frozen customer turns for that check.
2. Reverse-invokes the selected Chatbot or Chatflow with those turns.
3. Submits the observed assistant replies to NALV.
4. Returns NALV's evidence link and decision.

NALV owns planning, evaluation, and the stored run. The plugin does not score the bot itself.

## Installation and setup

1. Install **NALV** from the Dify Marketplace, or upload the `.difypkg` from a NALV release.
2. Add the NALV Endpoint.
3. Select the Chatbot or Chatflow to verify. Agent, New Agent, and Workflow apps are rejected as an unsupported target. That is not a behavioral FAIL.

## Connect with Google

1. Open the Endpoint URL Dify shows (path `/nalv`) and click **Connect NALV**.
2. Continue with Google on NALV. A personal workspace is created automatically if you do not have one.
3. Return to Dify. The Endpoint should show **NALV connected**.

You do not copy or paste a NALV connection key. Google credentials never enter this plugin.

## How to run a behavior check

1. Confirm NALV is connected and a Chatbot or Chatflow is selected.
2. Submit the Endpoint form, or `POST` JSON such as `{"app_id":"<dify-app-id>","app_mode":"chatflow"}`.
3. Open the returned Evidence URL in NALV. If you completed Connect in the same browser, Evidence opens without a second login.

The current hosted check uses a frozen three-turn customer script. NALV decides PASS / REVIEW / FAIL / RELEASE_BLOCKER from evidence. Infrastructure or evaluator failure stays REVIEW and is not treated as a behavioral FAIL.

## Disconnect

Click **Disconnect NALV** on the Endpoint page. That removes the connected state in Dify and asks NALV to revoke the active plugin surface token. Existing check runs remain available in NALV. Reload the Endpoint to confirm it stays disconnected until you Connect again.

## What data is sent to NALV

Connect sends a one-time connect session and, after Google sign-in, stores a scoped NALV surface token in Dify plugin session storage. Checks send the NALV-issued customer turns, observed assistant replies, conversation id, and Dify app id/mode to `https://app.nalv.ai`. The destination is fixed and not configurable.

The plugin does not send Dify workspace API keys. See [PRIVACY.md](./PRIVACY.md).

## Current capabilities and limits

Supported:

- Dify Chatbot (`chat`) and Chatflow (`advanced-chat` / `chatflow`)
- Connect NALV with Google identity
- Automatic personal workspace
- Blocking reverse invocation
- One conversation id reused across the frozen turns
- Evidence stored and evaluated by NALV

Not claimed and not included:

- Complete behavioral coverage
- Guaranteed correctness
- Production certifications
- Agent / Workflow targets

## Manual / advanced setup

A **NALV connection key** setting remains as an optional fallback for local development and troubleshooting. Prefer **Connect NALV**. Do not use a Dify Remote Debug key, Dify app API key, or invite token as that setting.

## Support

- Support: [support@nalv.ai](mailto:support@nalv.ai)
- Privacy: [privacy@nalv.ai](mailto:privacy@nalv.ai)
- Privacy policy: [PRIVACY.md](./PRIVACY.md)
- Source: https://github.com/nalv-ai/nalv-dify-plugin
