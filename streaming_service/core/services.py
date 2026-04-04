import os
import requests
import numpy as np
from google import genai
from google.genai import types

def generate_multimodal_embedding(text_overview, image_url, task_type="RETRIEVAL_DOCUMENT"):
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    model = os.getenv("MODEL")
    dimensionality = int(os.getenv("DIMENSIONALITY"))

    contents = []
    
    if text_overview:
        contents.append(types.Part.from_text(text=text_overview))
        
    if image_url:
        try:
            response = requests.get(image_url)
            if response.status_code == 200:
                image_part = types.Part.from_bytes(
                    data=response.content,
                    mime_type='image/jpeg',
                )
                contents.append(image_part)
        except Exception as e:
            print(f"Error downloading image: {e}")

    if not contents:
        return None, 0

    try:
        # Dimensionality and Task Type Settings
        config = types.EmbedContentConfig(
            output_dimensionality=dimensionality,
            task_type=task_type
        )

        token_info = client.models.count_tokens(
            model=model,
            contents=[types.Content(parts=contents)]
        )
        total_tokens = token_info.total_tokens

        # Embedding generation
        result = client.models.embed_content(
            model=model, 
            contents=contents,
            config=config
        )

        raw_vector = result.embeddings[0].values

        # MATHEMATICAL NORMALIZATION (Matryoshka)
        vector_np = np.array(raw_vector)
        normalized_vector = vector_np / np.linalg.norm(vector_np)

        return normalized_vector.tolist(), total_tokens
    except Exception as e:
        error_msg = str(e).lower()
        print(f"Error generating embedding with Gemini: {e}")
        if "429" in error_msg or "quota" in error_msg or "exhausted" in error_msg:
            raise ValueError("QUOTA_REACHED")
        return None, 0