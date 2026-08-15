from django.conf import settings
from openai import OpenAI

MODEL = 'nvidia/nemotron-3-ultra-550b-a55b'
MAX_TOKENS = 1024
TEMPERATURE = 1.0
TOP_P = 0.95

SYSTEM_PROMPT = (
    "You are EduTrellis AI, a friendly assistant embedded on the EduTrellis "
    "website (edutrellis.in). Keep answers clear and reasonably concise. "
    "You are a conversational assistant only — you have no access to any "
    "files, tools, databases, or the ability to take actions; you can only "
    "talk. If asked your name, who made you, or what model/company is behind "
    "you, always answer that you are EduTrellis AI, built for EduTrellis — "
    "never mention Nemotron, NVIDIA, or any other underlying model/vendor "
    "name, even if directly asked to reveal it."
)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(base_url='https://integrate.api.nvidia.com/v1', api_key=settings.NVIDIA_API_KEY)
    return _client


def stream_chat(messages):
    """messages: [{role: 'user'|'assistant', content: str}, ...] — the
    caller's conversation so far, already trimmed/sanitized. Yields text
    chunks as they arrive from the model. Thinking/reasoning is disabled
    (enable_thinking: False) so replies on a public page stay fast and cheap
    instead of spending tokens on a hidden reasoning trace for every message."""
    client = _get_client()
    full_messages = [{'role': 'system', 'content': SYSTEM_PROMPT}] + messages
    stream = client.chat.completions.create(
        model=MODEL,
        messages=full_messages,
        temperature=TEMPERATURE,
        top_p=TOP_P,
        max_tokens=MAX_TOKENS,
        stream=True,
        extra_body={'chat_template_kwargs': {'enable_thinking': False, 'force_nonempty_content': True}},
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        content = getattr(chunk.choices[0].delta, 'content', None)
        if content:
            yield content
