import os
import requests
from google import genai
from google.genai import types

def generate_multimodal_embedding(text_overview, image_url):

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    contents = []
    
    # 1. Agregar el texto
    if text_overview:
        contents.append(text_overview)
        
    # 2. Agregar la imagen
    if image_url:
        try:
            response = requests.get(image_url)
            if response.status_code == 200:
                # Gemini acepta la imagen en bytes
                image_part = types.Part.from_bytes(
                    data=response.content,
                    mime_type='image/jpeg',
                )
                contents.append(image_part)
        except Exception as e:
            print(f"Error descargando imagen: {e}")

    if not contents:
        return None

    try:
        result = client.models.embed_content(
            model='gemini-embedding-2-preview', 
            contents=contents,
            config=types.EmbedContentConfig(
                output_dimensionality=768,
                task_type="RETRIEVAL_DOCUMENT"
            )
        )
        return result.embeddings[0].values
    except Exception as e:
        print(f"Error generando embedding con Gemini: {e}")
        return None