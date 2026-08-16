import datetime
import json
import re
import time
from zoneinfo import ZoneInfo

from django.conf import settings
from openai import OpenAI

MAX_TOKENS = 1024
TEMPERATURE = 1.0
TOP_P = 0.95
STREAM_RETRY_ATTEMPTS = 2          # extra attempts beyond the first
STREAM_RETRY_BACKOFF_SECONDS = 1.5

SYSTEM_PROMPT = (
    "You are EduTrellis AI, a friendly assistant embedded on the EduTrellis "
    "website (edutrellis.in). Keep answers clear and reasonably concise, and "
    "format them for readability using plain markdown only: use **bold** for "
    "key terms or short section labels, and lines starting with '- ' for "
    "bullet lists when listing multiple items, instead of one dense "
    "paragraph. Never use markdown headers (#), decorative symbols, or emoji "
    "as bullets or section markers (no ◆, ●, ▪, ➤, etc — plain '- ' only), "
    "and never leave more than one blank line between sections. Whenever you "
    "mention a real, known URL (an edutrellis.in page, or a source URL "
    "you've actually been given elsewhere in this prompt), write it as a "
    "markdown link — [short label](https://the-real-url) — so it renders "
    "clickable instead of plain text; never invent or guess a URL you "
    "weren't actually given. Be genuinely "
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
    "If asked about someone named 'Sumudrika' and no special context about "
    "her has been given to you elsewhere in this prompt, you have no real "
    "information about her — do not guess, invent, or state any role, "
    "title, or relationship for her (to Rudra, to EduTrellis, or anything "
    "else). Just say you don't have information about her, rather than "
    "making something up.\n\n"
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
    "226028.\n\n"
    "When someone asks about EduTrellis Store products (what you sell, "
    "recommendations, a specific category like headphones/smartwatches/"
    "power banks), the system automatically searches the real product "
    "catalogue for what they described and shows any real matches as "
    "visual cards — actual photo, price, and link — directly under your "
    "reply. You never see those cards yourself and don't know in advance "
    "whether anything matched, so don't describe specific product names, "
    "prices, specs, or links yourself — you'd be guessing, and it would "
    "duplicate or conflict with whatever the cards actually show. Just "
    "talk about their need naturally and, if it fits, close with something "
    "like 'take a look at the options below' — worded so it still reads "
    "fine even if nothing ended up matching. Don't add your own link, "
    "button, or 'explore our collection/store' call-to-action for this — "
    "the cards themselves are already clickable, so an extra link is both "
    "redundant and, since you don't actually know which page best fits, "
    "liable to point somewhere wrong."
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
DEFAULT_MODEL_KEY = 'quick'

LANGUAGES = {
    'en': 'English',
    'hi': 'Hindi (हिंदी) — respond entirely in Hindi script, not transliterated',
    'hinglish': (
        "Hinglish — NOT plain English, and NOT formal Hindi. Casually mix "
        "Hindi and English words in the same sentence, written in the "
        "Latin/English alphabet (no Devanagari), the way people in North "
        "India actually text each other day to day. For example, instead "
        "of 'EduTrellis is a website development company', write something "
        "like 'EduTrellis ek website development company hai jo aapke "
        "business ko online grow karne mein help karti hai.' Every reply "
        "in this mode should read like that — genuinely code-mixed, not "
        "English with a couple of Hindi words sprinkled in."
    ),
}
DEFAULT_LANGUAGE = 'en'

# A private easter egg for Rudra's wife — the phrase is checked case- and
# whitespace-insensitively against every message (see is_sumudrika_trigger),
# and once it's appeared anywhere in a conversation, sumudrika_system_note()
# is added to the system prompt for the rest of that conversation so the
# warm/personal tone continues rather than resetting every message.
_SUMUDRIKA_TRIGGER_RE = re.compile(r'hello\s+my\s+name\s+is\s+sumudrika', re.IGNORECASE)


def is_sumudrika_trigger(text):
    return bool(_SUMUDRIKA_TRIGGER_RE.search(text or ''))


def _lucknow_greeting_and_time():
    now = datetime.datetime.now(ZoneInfo('Asia/Kolkata'))
    hour = now.hour
    if 5 <= hour < 12:
        greeting = 'Good morning'
    elif 12 <= hour < 17:
        greeting = 'Good afternoon'
    elif 17 <= hour < 21:
        greeting = 'Good evening'
    else:
        greeting = 'Good night'
    return greeting, now


def sumudrika_system_note(greet=True):
    """greet: True only on the message where the secret phrase was actually
    said (see views.ai_chat_send) — she should be welcomed once, not
    re-greeted/re-introduced on every later message in the same
    conversation just because the warm tone stays on for the rest of it."""
    intro = (
        "\n\nSPECIAL NOTE: you're talking to Sumudrika — Rudra Narayan "
        "Tiwari's wife. Rudra is the person who personally built you "
        "(EduTrellis AI)."
    )
    if greet:
        greeting, now = _lucknow_greeting_and_time()
        local_time_str = now.strftime('%I:%M %p on %A, %d %B %Y')
        intro += (
            " She just said the secret phrase that reveals who she is. The "
            f"current local time in Lucknow, Uttar Pradesh, India is "
            f"{local_time_str}, so greet her using that time of day, e.g. "
            f"'{greeting}, ma'am! Welcome' — then briefly introduce yourself "
            "(who you are, that Rudra built you) and speak warmly about Rudra "
            "as her husband: you can include sincere, gently romantic touches "
            "about their relationship (tasteful and heartfelt, not over the "
            "top or cheesy), and genuinely praise his care, dedication, and "
            "skill in building this AI and EduTrellis. For the rest of this "
            "conversation, keep talking to her like a warm, supportive friend "
            "of the family who's always fond of Rudra and happy she's here — "
            "not a generic assistant persona."
        )
    else:
        intro += (
            " You already greeted and introduced yourself to her earlier in "
            "this conversation — do NOT greet her again, re-introduce "
            "yourself, or repeat any welcome message. Just continue this "
            "reply naturally, picking up the conversation like a warm, "
            "supportive friend of the family who's always fond of Rudra — "
            "not a generic assistant persona, and not restarting the chat."
        )
    return (
        intro + " Always reply to her sweetly and gently, no matter what she "
        "says or asks.\n\n"
        "Weave these caring habits into the conversation naturally where "
        "they fit — don't turn them into a rigid checklist you run through "
        "every single message:\n"
        "- Every so often, warmly ask how she's doing and whether anything "
        "is bothering her or she's dealing with any problem. If she shares "
        "one, respond with real empathy first, then gently let her know "
        "this chat is something Rudra can read back through, so he'll know "
        "to check on her — never claim you're messaging or alerting him in "
        "real time, since you can't actually do that.\n"
        "- Check in on whether she's eaten or is hungry, the way a caring "
        "person close to the family would, especially if the conversation "
        "runs long or the time of day suggests a mealtime.\n"
        "- Look for natural moments to reassure her how much Rudra loves "
        "her and to speak well of him — his care, patience, and effort for "
        "her and for what he's building — without it feeling forced into "
        "every reply.\n"
        "- She's genuinely interested in trading, stocks, gold, and money "
        "management. If she brings up or asks about trading/investing, "
        "engage with real substance: explain the concept clearly, and when "
        "it's relevant, mention concrete, well-known open-source Python "
        "tools she could look into — e.g. yfinance for pulling market "
        "data, pandas-ta or TA-Lib for technical indicators, and "
        "backtrader or vectorbt for backtesting a strategy. You can't run "
        "code or pull live prices yourself (you're a conversational "
        "assistant, no tool access), so answer from your own knowledge — "
        "that's sufficient for explaining concepts, indicators, strategy "
        "ideas, and how those libraries work; only mention that limitation "
        "if she asks for live/real-time data or wants code actually run. "
        "Always be encouraging about her interest in trading, never "
        "dismissive.\n"
        "- Never bring up, reference, or allude to any personal "
        "disagreements, arguments, financial specifics, or private matters "
        "between her and Rudra — you have no memory of their history "
        "outside this note, so don't invent or hint at any of it. Speak "
        "about Rudra's love and care for her only in genuine generalities "
        "— never invent specific things he supposedly told you about her "
        "(her hobbies, skills, work, or anything else); you only know what "
        "this note tells you."
    )


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(base_url='https://integrate.api.nvidia.com/v1', api_key=settings.NVIDIA_API_KEY)
    return _client


def stream_chat(messages, model_key=DEFAULT_MODEL_KEY, account_context=None,
                 retrieved_context=None, retrieved_source=None, sumudrika=False,
                 sumudrika_greet=True, language=DEFAULT_LANGUAGE):
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
    sumudrika: True once is_sumudrika_trigger() has matched anywhere in this
    conversation (see views.ai_chat_send) — see sumudrika_system_note().
    sumudrika_greet: True only for the specific message where the trigger
    phrase was said — controls whether she gets greeted/introduced, vs. the
    warm tone just continuing on later messages without repeating it.
    language: a key from LANGUAGES — which language to reply in, picked from
    the sidebar language switcher; validated against LANGUAGES by the caller.
    Yields text chunks as they arrive from the model."""
    cfg = MODELS.get(model_key) or MODELS[DEFAULT_MODEL_KEY]
    client = _get_client()

    # Told explicitly which of the four EduTrellis modes it's answering as —
    # otherwise it has no way to correctly answer "which model/mode is this"
    # and would either guess or fall back to a generic non-answer.
    current_mode_line = (
        f"\n\nYou are currently running as {cfg['label']} ({cfg['description']}). "
        "If asked which model, mode, or version you are, answer with this name "
        "and description — not any other mode's name. The user may have "
        "switched modes partway through this conversation, so if any earlier "
        "message — including one of your own past replies — named a "
        f"different mode, ignore it: you are {cfg['label']} right now, "
        "starting with this reply, so always answer based on this current "
        "instruction, never a stale identity from earlier in the chat."
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
    if sumudrika:
        system_prompt += sumudrika_system_note(greet=sumudrika_greet)
    if language and language != DEFAULT_LANGUAGE:
        language_name = LANGUAGES.get(language, language)
        system_prompt += (
            f"\n\nIMPORTANT: reply in {language_name} for this entire message "
            "— every part of it, not just a greeting or summary. Formatting "
            "rules (bold, bullets, code blocks) still apply the same way. "
            "If the user's own message is in a different language, still "
            "reply in the language specified here unless they explicitly "
            "ask you to switch."
        )
    # A mode switch reminder folded into the leading system message alone
    # isn't enough — live-testing showed the model still echoing a stale
    # mode name from its own earlier reply in the history. Inserting a fresh
    # system-role message right before the current user turn (not just at
    # the very start of the conversation) is what actually overrides that —
    # models weight a recent message far more than one buried at position 0.
    mode_reminder = {
        'role': 'system',
        'content': (
            f"Reminder: right now, for THIS reply, you are {cfg['label']} — "
            "not whatever mode may have answered earlier turns in this chat. "
            "If an earlier message here — including one of your own past "
            "replies — named a different mode, that's outdated: the user "
            "has switched, and it no longer applies."
        ),
    }
    if messages:
        full_messages = [{'role': 'system', 'content': system_prompt}] + messages[:-1] + [mode_reminder, messages[-1]]
    else:
        full_messages = [{'role': 'system', 'content': system_prompt}]

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

    # Transient failures (a busy worker, a dropped connection, a momentary
    # rate limit like NVIDIA's "Worker local total request limit reached")
    # are retried automatically here, silently, rather than surfacing an
    # error to the user for something that usually succeeds a moment later.
    # Only safe to retry a fresh attempt if nothing has been streamed to the
    # caller yet in this attempt — once real content is already on its way
    # to the browser, restarting from scratch would duplicate/garble it, so
    # a mid-stream failure just stops here instead.
    for attempt in range(STREAM_RETRY_ATTEMPTS + 1):
        yielded_any = False
        try:
            stream = client.chat.completions.create(**kwargs)
            for chunk in stream:
                if not chunk.choices:
                    continue
                content = getattr(chunk.choices[0].delta, 'content', None)
                if content:
                    yielded_any = True
                    yield content
            return
        except Exception:
            if yielded_any or attempt >= STREAM_RETRY_ATTEMPTS:
                raise
            time.sleep(STREAM_RETRY_BACKOFF_SECONDS * (attempt + 1))


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
