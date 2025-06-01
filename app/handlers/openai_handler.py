import openai
from typing import Tuple, List, Dict
from app.core.config import settings
from app.core.logging import setup_logger

logger = setup_logger(__name__)

openai.api_key = settings.openai_api_key


async def get_bot_response(
    prompt: str,
    *,
    model: str = "gpt-3.5-turbo",
    max_tokens: int = 150,
    n: int = 1,
    stop: List[str] | None = None,
    temperature: float = 0.7,
) -> Tuple[str | None, int]:
    """Return a completion for ``prompt`` using OpenAI's completion API.

    This helper exposes common parameters so callers can control the length of
    the generated text and other generation options.
    """

    try:
        completions = openai.Completion.create(
            engine=model,
            prompt=prompt,
            max_tokens=max_tokens,
            n=n,
            stop=stop,
            temperature=temperature,
        )

        choice = completions.choices[0]
        response_text = choice.text.strip()
        tokens_used = completions.usage.get("total_tokens", 0)
        return response_text, tokens_used

    except Exception as e:  # pragma: no cover - network issues
        logger.error("Error in OpenAI handler: %s", e)
        return None, 0


async def create_chat_interaction(
    messages: List[Dict[str, str]],
    *,
    max_tokens: int = 150,
    model: str = "gpt-3.5-turbo",
    n: int = 1,
    stop: List[str] | None = None,
    temperature: float = 0.7,
) -> Dict[str, str]:
    """
    Function to create a new chat interaction with OpenAI API.

    Args:
    model (str): Model name to be used for the chat.
    messages (List[Dict[str, str]]): List of message objects. Each object should have "role" and "content" fields.

    Returns:
    Dict[str, str]: Response from OpenAI API.

    The system role's content field should be from the "prompt" field in the Filter.  
    The "user" role should be the incoming message
    The "assistant" role should be the response

    """

    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            n=n,
            stop=stop,
            temperature=temperature,
        )

        return response

    except Exception as e:
        print(f"Failed to create chat interaction: {e}")
        # create a fake interaction if we forget to include the handle Key
        '''
        Failed to create chat interaction: No API key provided. You can set your API key in code using 'openai.api_key = <API-KEY>', or you can set the environment variable OPENAI_API_KEY=<API-KEY>). If your API key is stored in a file, you can point the openai module at it with 'openai.api_key_path = <PATH>'. You can generate API keys in the OpenAI web interface. See https://platform.openai.com/account/api-keys for details.
        '''
        if openai.api_key is None:
            logger.warning("OpenAI API key not configured. Set 'openai_api_key' in config.yaml and restart Norman.")
            response = {}
            response['model'] = "norman"
            response['choices'] = []
            lmsg = {}
            lmsg['message'] = {}
            lmsg['message']['content'] = 'Please add your OpenAI API key in config.yaml under openai_api_key and restart the program.'
            response['error'] = True
            response['usage'] = {}
            response['usage']['prompt_tokens'] = 0
            response['usage']['completion_tokens'] = 0
            response['choices'].append(lmsg)
            return response

        return None
