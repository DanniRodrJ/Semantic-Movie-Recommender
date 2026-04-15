import os
import requests
import time
from dotenv import load_dotenv
from django.core.management.base import BaseCommand
from core.models import Movie, Actor
from core.services import generate_multimodal_embedding

load_dotenv()

class Command(BaseCommand):
    help = 'Populate the database with popular movies from TMDB API'

    def add_arguments(self, parser):
        parser.add_argument(
            '--pages',
            type=int,
            default=3,
            help='Number of pages to fetch (20 movies per page)'
        )
        parser.add_argument(
            '--language',
            type=str,
            default='en-US',  # 'es-ES'
            help='Language for movie data'
        )

    def handle(self, *args, **options):
        api_key = os.getenv('TMDB_API_KEY')  
        if not api_key:
            self.stdout.write(self.style.ERROR('TMDB_API_KEY no está en .env'))
            return

        pages = options['pages']
        language = options['language']
        base_url = "https://api.themoviedb.org/3"

        self.stdout.write(self.style.SUCCESS(f'Loading: {pages} pages in {language}'))

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
                self.stdout.write(self.style.ERROR(f'Error en página {page}: {response.text}'))
                continue

            movies = response.json()['results']

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
                    self.stdout.write(self.style.NOTICE(f'Omitiendo Gemini para: {title} (Vector ya existe)'))
                    vector = existing_movie.embedding
                    tokens_used = existing_movie.embedding_tokens
                else:            
                    self.stdout.write(f'Generando vector multimodal para: {title}...')
                    full_poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                    
                    try:
                        vector, tokens_used = generate_multimodal_embedding(rich_text, full_poster_url)
                        time.sleep(2)
                    except ValueError as e:
                        if "QUOTA_REACHED" in str(e):
                            self.stdout.write(self.style.ERROR('\n🚨 API LIMIT REACHED 🚨\nThe previous movies were saved successfully.'))
                            import sys
                            sys.exit(0)

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
                    self.stdout.write(self.style.SUCCESS(f'Created: {title} (ID: {tmdb_id})'))
                else:
                    self.stdout.write(self.style.WARNING(f'Updated: {title}'))

                time.sleep(0.35) 

        self.stdout.write(self.style.SUCCESS('Population completed!'))