import os
import requests
import time
import logging
from celery import shared_task
from core.models import Movie, Actor
from core.services import generate_multimodal_embedding

logger = logging.getLogger(__name__)

def send_telegram_alert(message):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    chat_id = os.getenv('TELEGRAM_CHAT_ID')
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, data={'chat_id': chat_id, 'text': message})

@shared_task
def fetch_and_vectorize_movies(pages=3, language='en-US'):
    api_key = os.getenv('TMDB_API_KEY')  
    if not api_key:
        logger.error('TMDB_API_KEY is not set in the environment variables.')
        return "Error: Missing TMDB API Key"

    base_url = "https://api.themoviedb.org/3"
    movies_processed = 0
    
    logger.info(f'Starting automated pipeline: Loading {pages} pages in {language}')

    for page in range(1, pages + 1):
        # 1. Get popular movies
        discover_url = f"{base_url}/discover/movie"
        params = {
            'api_key': api_key,
            'language': language,
            'sort_by': 'popularity.desc',
            'page': page,
            'include_adult': 'false',
        }
        response = requests.get(discover_url, params=params)

        if response.status_code != 200:
            logger.error(f'Error fetching page {page}: {response.text}')
            continue

        movies = response.json().get('results', [])

        for movie_data in movies:
            tmdb_id = movie_data['id']

            # 2. Get details + credits
            details_url = f"{base_url}/movie/{tmdb_id}"
            details_params = {
                'api_key': api_key,
                'language': language,
                'append_to_response': 'credits,videos',
            }
            details_resp = requests.get(details_url, params=details_params)

            if details_resp.status_code != 200:
                continue

            details = details_resp.json()

            title = details.get('title', '')
            runtime = details.get('runtime')
            overview = details.get('overview', '')
            release_date = details.get('release_date') or None
            release_year = release_date.split('-')[0] if release_date else 'Unknown'
            poster_path = details.get('poster_path', '')
            backdrop_path = details.get('backdrop_path', '')
            genres = details.get('genres', [])  
            vote_average = details.get('vote_average', 0.0)
            popularity = details.get('popularity', 0.0)
            credits = details.get('credits', {})
            
            director = ''
            for crew in credits.get('crew', []):
                if crew.get('job') == 'Director':
                    director = crew.get('name', '')
                    break
                    
            genres_ = ", ".join([g.get('name', '') for g in genres])
            actors_ = ", ".join([cast['name'] for cast in credits.get('cast', [])[:5]])
           
            rich_text = f'Title: {title} ({release_year}). Genres: {genres_}. Actors: {actors_}. Director: {director}. Overview: {overview}.'
    
            videos = details.get('videos', {}).get('results', [])
            video_url = None
            for video in videos:
                if video.get('site') == 'YouTube' and video.get('type') == 'Trailer':
                    if video.get('official'):
                        key = video.get('key')
                        video_url = f"https://www.youtube.com/embed/{key}"
                        break
                    elif not video_url:
                        key = video.get('key')
                        video_url = f"https://www.youtube.com/embed/{key}"
                        
            existing_movie = Movie.objects.filter(tmdb_id=tmdb_id).first()
            
            if existing_movie and existing_movie.embedding is not None:
                logger.info(f'Skipping Gemini for: {title} (Vector already exists)')
                vector = existing_movie.embedding
                tokens_used = existing_movie.embedding_tokens
            else:            
                logger.info(f'Generating multimodal vector for: {title}...')
                full_poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                
                try:
                    vector, tokens_used = generate_multimodal_embedding(rich_text, full_poster_url)
                    time.sleep(2)
                except ValueError as e:
                    if "QUOTA_REACHED" in str(e):
                        logger.error('🚨 API LIMIT REACHED 🚨 The previous movies were saved successfully. Stopping pipeline for today.')
                        return "Stopped due to API Quota"
                    else:
                        logger.error(f'Error generating embedding for {title}: {e}')
                        continue

                time.sleep(2)

            movie, created = Movie.objects.update_or_create(
                tmdb_id=tmdb_id,
                defaults={
                    'title': title,
                    'overview': overview,
                    'director': director,
                    'release_date': release_date,
                    'poster_path': poster_path,
                    'backdrop_path': backdrop_path,
                    'genres': genres,
                    'vote_average': vote_average,
                    'popularity': popularity,
                    'video_url': video_url,
                    'runtime': runtime,
                    'embedding': vector,
                    'embedding_tokens': tokens_used if vector is not None else 0,
                }
            )
            
            for cast in credits.get('cast', [])[:5]:
                actor_name = cast.get('name')
                if not actor_name:
                    continue

                actor_tmdb_id = cast.get('id') 
                actor, _ = Actor.objects.get_or_create(
                    name=actor_name,
                    defaults={
                        'tmdb_id': actor_tmdb_id,
                        'profile_path': cast.get('profile_path'),
                        'popularity': cast.get('popularity', 0.0),
                    }
                )
                movie.actors.add(actor)

            if created:
                logger.info(f'Created: {title} (ID: {tmdb_id})')
            else:
                logger.warning(f'Updated: {title}')

            movies_processed += 1
            time.sleep(0.35) 

    success_msg = f"✅ Pipeline finished. {movies_processed} new movies added and vectorized."
    logger.info(success_msg)
    send_telegram_alert(success_msg)
    logger.info('Population pipeline completed successfully!')
    return "Success"