from django.conf import settings
from openai import OpenAI

MAX_TOKENS = 1024
TEMPERATURE = 1.0
TOP_P = 0.95

SYSTEM_PROMPT = (
    "You are EduTrellis AI, a friendly assistant embedded on the EduTrellis "
    "website (edutrellis.in). Keep answers clear and reasonably concise, and "
    "format them for readability: use **bold** for key terms, and short "
    "bullet or numbered lists when listing multiple items, instead of one "
    "dense paragraph. You are a conversational assistant only — you have no "
    "access to any files, tools, databases, or the ability to take actions; "
    "you can only talk.\n\n"
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


def stream_chat(messages, model_key=DEFAULT_MODEL_KEY):
    """messages: [{role: 'user'|'assistant', content: str | list}, ...] — the
    caller's conversation so far, already trimmed/sanitized. 'content' is a
    plain string for text-only turns, or a list of OpenAI-style content
    blocks ({'type': 'text', ...} / {'type': 'image_url', ...}) for a turn
    that included an image. Yields text chunks as they arrive from the
    model."""
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
