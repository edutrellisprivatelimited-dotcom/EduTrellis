import json

from django.conf import settings
from openai import OpenAI

MAX_TOKENS = 1024
TEMPERATURE = 1.0
TOP_P = 0.95

SYSTEM_PROMPT = (
    "You are EduTrellis AI, a friendly assistant embedded on the EduTrellis "
    "website (edutrellis.in). Keep answers clear and reasonably concise, and "
    "format them for readability using plain markdown only: use **bold** for "
    "key terms or short section labels, and lines starting with '- ' for "
    "bullet lists when listing multiple items, instead of one dense "
    "paragraph. Never use markdown headers (#), decorative symbols, or emoji "
    "as bullets or section markers (no ◆, ●, ▪, ➤, etc — plain '- ' only), "
    "and never leave more than one blank line between sections. Be genuinely "
    "understanding, not just polite — read between the lines of what "
    "someone actually needs, especially if they sound frustrated, unsure, "
    "or are describing a problem rather than asking a direct question. When "
    "a request is vague, broad, or could reasonably go in more than one "
    "direction (e.g. 'help me with my website', 'I have an issue', 'what "
    "should I do'), don't guess and dump a generic wall of information — "
    "ask one short, specific clarifying question first so your answer "
    "actually fits their situation. Skip the clarifying question when the "
    "request is already clear and specific, or after they've answered once "
    "— don't interrogate them or ask more than one clarifying question in a "
    "row. You are a "
    "conversational assistant only — you have no "
    "access to any files, tools, or the ability to take actions (you can't "
    "place orders, edit a cart, change account details, etc.), you can only "
    "talk. The one exception: if the user is logged in, you're given a "
    "read-only snapshot of their own EduTrellis Store cart and recent orders "
    "(see below) so you can answer questions about it — you still can't "
    "change anything, and you never have access to any other user's data.\n\n"
    "If asked your name, who made you, who built you, or what model/company "
    "is behind you, always answer that you are EduTrellis AI, built for "
    "EduTrellis by Rudra Narayan Tiwari — never mention Nemotron, NVIDIA, "
    "Llama, Meta, or any other underlying model/vendor name, even if "
    "directly asked to reveal it. If the user is chatting with one of your "
    "specialized modes (Quick, Code, Vision), refer to it by its EduTrellis "
    "name only.\n\n"
    "Background knowledge about EduTrellis, for when it's relevant to the "
    "conversation (don't recite this unprompted):\n"
    "- EduTrellis is a website development and digital growth company based "
    "in Lucknow, Uttar Pradesh, India, founded in 2020 by its Founder & CEO, "
    "Vijay Tiwari. (Vijay Tiwari founded the company itself — a separate "
    "fact from this AI chat feature, which was built by Rudra Narayan "
    "Tiwari.)\n"
    "- edutrellis.in (the homepage) is the main business site: website "
    "design & development, website management, SEO, Meta Ads, Google "
    "Business Profile setup, WordPress and Django development, logo/banner "
    "design, social media handle setup, and digital marketing services.\n"
    "- edutrellis.in/websitecreation is a dedicated page for getting a "
    "custom website built — from single-page static business sites to full "
    "dynamic e-commerce stores and large custom web apps — with a free "
    "consultation, strategy, build, and ongoing growth process.\n"
    "- edutrellis.in/store is EduTrellis Store, the company's own online "
    "gadget store selling earbuds, headphones, smartwatches, keyboards, "
    "power banks, chargers, and smart home devices across India, with "
    "Razorpay/COD payment options and order tracking.\n"
    "- edutrellis.in/AI is this AI chat page.\n"
    "- Contact: support@edutrellis.in, or WhatsApp/call +91 96959 53183. "
    "Office: P-109, Prembagh, Shahpur, Chinhat, Lucknow, Uttar Pradesh "
    "226028."
)

CODE_SYSTEM_SUFFIX = (
    "\n\nYou are currently in EduTrellis Code mode: prioritize correct, "
    "working code over long explanations. Use fenced code blocks (```) for "
    "any code, name the language, and keep prose commentary brief unless "
    "asked to elaborate."
)

# Every model here is verified directly against the live NVIDIA API key this
# app uses — being listed in NVIDIA's catalog doesn't mean a given account
# actually has invoke access to it, and several plausible choices (dedicated
# "coder" checkpoints, nvidia/vila, mistral-large) 404'd for this account.
# 'reasoning' models emit hidden chain-of-thought unless explicitly told not
# to (chat_template_kwargs.enable_thinking=False) — without that flag they
# dump raw "Let me think..." text into the reply instead of a clean answer.
MODELS = {
    'ultra': {
        'id': 'nvidia/nemotron-3-ultra-550b-a55b',
        'label': 'EduTrellis Ultra',
        'description': 'Most capable — best for detailed or complex questions.',
        'reasoning': True,
        'vision': False,
    },
    'quick': {
        'id': 'nvidia/nemotron-3-nano-30b-a3b',
        'label': 'EduTrellis Quick',
        'description': 'Fast and lightweight — best for short, simple questions.',
        'reasoning': True,
        'vision': False,
    },
    'light': {
        'id': 'nvidia/nemotron-3-nano-30b-a3b',
        'label': 'EduTrellis Light',
        'description': "Fastest — answers from EduTrellis's saved knowledge first, and searches the web if it isn't there.",
        'reasoning': True,
        'vision': False,
    },
    'code': {
        'id': 'meta/llama-3.1-70b-instruct',
        'label': 'EduTrellis Code',
        'description': 'Tuned for coding, debugging, and technical questions.',
        'reasoning': False,
        'vision': False,
    },
    'vision': {
        'id': 'nvidia/nemotron-nano-12b-v2-vl',
        'label': 'EduTrellis Vision',
        'description': 'Understands images — used automatically when you attach one.',
        'reasoning': False,
        'vision': True,
    },
}
DEFAULT_MODEL_KEY = 'ultra'

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(base_url='https://integrate.api.nvidia.com/v1', api_key=settings.NVIDIA_API_KEY)
    return _client


def stream_chat(messages, model_key=DEFAULT_MODEL_KEY, account_context=None,
                 retrieved_context=None, retrieved_source=None):
    """messages: [{role: 'user'|'assistant', content: str | list}, ...] — the
    caller's conversation so far, already trimmed/sanitized. 'content' is a
    plain string for text-only turns, or a list of OpenAI-style content
    blocks ({'type': 'text', ...} / {'type': 'image_url', ...}) for a turn
    that included an image. account_context, when given, is a short summary
    of the logged-in user's own cart/orders (already scoped to that user by
    the caller) — never fetched or trusted from anywhere but the server side.
    retrieved_context/retrieved_source (EduTrellis Light only) is whatever
    myapp.light_mode found for this turn — either a knowledge_base match or
    a fresh web_search result — already retrieved and bounded by the caller.
    Yields text chunks as they arrive from the model."""
    cfg = MODELS.get(model_key) or MODELS[DEFAULT_MODEL_KEY]
    client = _get_client()

    # Told explicitly which of the four EduTrellis modes it's answering as —
    # otherwise it has no way to correctly answer "which model/mode is this"
    # and would either guess or fall back to a generic non-answer.
    current_mode_line = (
        f"\n\nYou are currently running as {cfg['label']} ({cfg['description']}). "
        "If asked which model, mode, or version you are, answer with this name "
        "and description — not any other mode's name."
    )
    system_prompt = SYSTEM_PROMPT + current_mode_line + (CODE_SYSTEM_SUFFIX if model_key == 'code' else '')
    if account_context:
        system_prompt += (
            "\n\nThe user is logged into their EduTrellis Store account. Here is "
            "their real account data as of right now — use it only if they ask "
            "about their cart, orders, wallet, or account; don't recite it "
            "unprompted, and never state a cart/order detail that isn't listed "
            "here:\n" + account_context
        )
    if retrieved_context:
        source_label = "EduTrellis's saved knowledge base" if retrieved_source == 'knowledge_base' else 'a live web search'
        system_prompt += (
            f"\n\nFor this reply, here is relevant information retrieved from "
            f"{source_label} — use it as your primary source for factual "
            "claims in this answer instead of guessing from general "
            "knowledge. If it doesn't actually answer the question, say so "
            "rather than making something up:\n" + retrieved_context
        )
    full_messages = [{'role': 'system', 'content': system_prompt}] + messages

    kwargs = dict(
        model=cfg['id'],
        messages=full_messages,
        temperature=TEMPERATURE,
        top_p=TOP_P,
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    if cfg['reasoning']:
        # Disabled so replies on a public page stay fast and cheap instead of
        # spending tokens (and screen space) on a hidden reasoning trace.
        kwargs['extra_body'] = {'chat_template_kwargs': {'enable_thinking': False, 'force_nonempty_content': True}}

    stream = client.chat.completions.create(**kwargs)
    for chunk in stream:
        if not chunk.choices:
            continue
        content = getattr(chunk.choices[0].delta, 'content', None)
        if content:
            yield content


# ── GitHub mode: repo-aware code changes, driven by a plain-English prompt ──
# Two deterministic LLM calls rather than a general multi-turn tool-use loop
# (NVIDIA's OpenAI-compatible endpoint doesn't have verified tool-calling
# support for these models) — phase 1 picks which existing files are worth
# reading, phase 2 turns the instruction + those files' content into a
# concrete list of file operations. The caller (views.ai_github_send) is
# responsible for actually applying each operation via github_ops and for
# enforcing the blocked-path list — this module only ever proposes JSON.
GITHUB_MODEL_KEY = 'code'
GITHUB_FILE_LIST_CAP = 4000  # paths sent to the model per call
GITHUB_SELECT_FILE_CAP = 8   # files the model may ask to read per request


def _github_llm_json(client, model_id, system, user_content):
    resp = client.chat.completions.create(
        model=model_id,
        messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user_content}],
        temperature=0.2,
        top_p=0.9,
        max_tokens=4096,
        stream=False,
    )
    text = (resp.choices[0].message.content or '').strip()
    if text.startswith('```'):
        text = text.split('```', 2)[1]
        if text.lower().startswith('json'):
            text = text[4:]
        text = text.rsplit('```', 1)[0]
    return json.loads(text)


def github_select_files(prompt, file_paths):
    """Ask which existing files (out of the real repo file list) are worth
    reading before proposing a change. Result is always filtered against the
    real path list, so the model can't cause a lookup of a path it invented."""
    client = _get_client()
    system = (
        "You are a senior software engineer with access to a Git repository's "
        "file tree. Given the user's instruction, decide which existing files "
        "you need to read the full content of before you can make the change. "
        f"Reply with ONLY a JSON array of up to {GITHUB_SELECT_FILE_CAP} file "
        "paths, copied exactly from the provided file list — no other text, "
        "no markdown fences. If you don't need to read anything, reply []."
    )
    listing = '\n'.join(file_paths[:GITHUB_FILE_LIST_CAP])
    user_content = f"Instruction: {prompt}\n\nRepository files:\n{listing}"
    try:
        result = _github_llm_json(client, MODELS[GITHUB_MODEL_KEY]['id'], system, user_content)
    except Exception:
        return []
    if not isinstance(result, list):
        return []
    valid = set(file_paths)
    return [p for p in result if isinstance(p, str) and p in valid][:GITHUB_SELECT_FILE_CAP]


def github_plan_changes(prompt, file_paths, file_contents):
    """file_contents: {path: content} for whatever github_select_files asked
    for. Returns {'summary', 'commit_message', 'operations': [...]}, or
    raises if the model's reply isn't valid JSON — the caller decides how to
    surface that as a chat reply."""
    client = _get_client()
    system = (
        "You are a senior software engineer making a direct commit to a Git "
        "repository on the user's instruction. Reply with ONLY a JSON object "
        "(no markdown fences, no other text) of exactly this shape:\n"
        '{"summary": "one or two sentences describing the change, for the '
        'user", "commit_message": "a short git commit message", '
        '"operations": [{"action": "update"|"create"|"delete", "path": '
        '"path/to/file", "content": "full new file content (omit for '
        'delete)"}]}\n'
        "Rules: 'content' for update/create must be the COMPLETE new file "
        "content, never a diff or a snippet with '...'. Only touch files "
        "that are actually necessary. Never invent a path that doesn't fit "
        "this project's structure. If the instruction is unclear, unsafe, or "
        "you don't have enough information, return an empty operations array "
        "and explain why in 'summary'."
    )
    listing = '\n'.join(file_paths[:GITHUB_FILE_LIST_CAP])
    context_blocks = '\n\n'.join(f"--- {path} ---\n{content}" for path, content in file_contents.items())
    user_content = (
        f"Instruction: {prompt}\n\nRepository file list:\n{listing}\n\n"
        f"Current content of the files you asked to see:\n{context_blocks}"
    )
    return _github_llm_json(client, MODELS[GITHUB_MODEL_KEY]['id'], system, user_content)
