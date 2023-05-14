
import openai
from typing import Tuple, List, Dict
from app.core.config import settings

openai.api_key = settings.openai_api_key

'''
# TODO: all users to specify token length, number of tokens, etc. 
async def get_bot_response(prompt: str, model: str = 'gpt-3.5-turbo') -> Tuple[str, int]:
    try:
        completions = openai.Completion.create(
            engine=model,
            prompt=prompt,
            max_tokens=150,
            n=1,
            stop=None,
            temperature=0.7,
        )

        choice = completions.choices[0]
        response_text = choice.text.strip()
        tokens_used = choice.usage['total_tokens']

        return response_text, tokens_used

    except Exception as e:
        print(f"Error in OpenAI handler: {e}")
        return None, 0
'''


async def create_chat_interaction(messages: List[Dict[str, str]], max_tokens: int=150, model: str = 'gpt-3.5-turbo') -> Dict[str, str]:
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
            max_tokens=max_tokens
        )

        return response

    except Exception as e:
        print(f"Failed to create chat interaction: {e}")
        # create a fake interaction if we forget to include the handle Key
        '''
        Failed to create chat interaction: No API key provided. You can set your API key in code using 'openai.api_key = <API-KEY>', or you can set the environment variable OPENAI_API_KEY=<API-KEY>). If your API key is stored in a file, you can point the openai module at it with 'openai.api_key_path = <PATH>'. You can generate API keys in the OpenAI web interface. See https://platform.openai.com/account/api-keys for details.
        '''
        if openai.api_key is None:
            response = {}
            response['model'] = "norman"
            response['choices'] = []
            lmsg = {}
            lmsg['message'] = {}
            # todo: tell the user to set the config file
            lmsg['message']['content'] = 'Please add your OpenAI api key in the config.yaml under openai_api_key, and restart the program'
            response['error'] = True
            response['usage'] = {}
            response['usage']['prompt_tokens'] = 0
            response['usage']['completion_tokens'] = 0
            response['choices'].append(lmsg)
            return response

        return None
