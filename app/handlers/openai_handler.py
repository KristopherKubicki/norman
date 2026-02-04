from typing import List, Dict, Any
import anyio
from openai import OpenAI
from app.core.config import settings
from app.core.logging import setup_logger
from app.core.exceptions import APIError

logger = setup_logger(__name__)

DEFAULT_MODEL = settings.openai_default_model
DEFAULT_MAX_TOKENS = settings.openai_max_tokens


def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key)


def _response_to_dict(response: Any) -> Dict[str, Any]:
    choices = []
    for choice in response.choices or []:
        content = getattr(choice.message, "content", None)
        choices.append({"message": {"content": content}})

    usage = response.usage
    usage_dict = {
        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
        "completion_tokens": getattr(usage, "completion_tokens", 0),
    }

    return {
        "model": response.model,
        "choices": choices,
        "usage": usage_dict,
        "headers": {},
    }


async def create_chat_interaction(
    messages: List[Dict[str, str]],
    max_tokens: int = DEFAULT_MAX_TOKENS,
    model: str = DEFAULT_MODEL,
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
        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured.")
        response = await anyio.to_thread.run_sync(
            lambda: _client().chat.completions.create(
                model=model, messages=messages, max_tokens=max_tokens
            )
        )
        return _response_to_dict(response)

    except Exception as e:
        logger.error("Failed to create chat interaction: %s", e)
        if not settings.openai_api_key:
            logger.warning(
                "OpenAI API key not configured. Set 'openai_api_key' in config.yaml and restart Norman."
            )
            response = {
                "model": "norman",
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Please add your OpenAI API key in config.yaml under openai_api_key and restart the program."
                            )
                        }
                    }
                ],
                "error": True,
                "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            }
            return response

        raise APIError("Failed to communicate with OpenAI") from e
