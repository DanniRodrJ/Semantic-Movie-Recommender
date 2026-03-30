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

        self.stdout.write(self.style.SUCCESS(f'Iniciando populate: {pages} páginas en {language}'))

        for page in range(1, pages + 1):
            # 1. Obtener películas populares
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

                # 2. Obtener detalles + credits
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

                # Extraer datos
                title = details.get('title', '')
                overview = details.get('overview', '')
                release_date = details.get('release_date') or None
                poster_path = details.get('poster_path', '')
                backdrop_path = details.get('backdrop_path', '')
                genres = details.get('genres', [])  # lista de dicts
                vote_average = details.get('vote_average', 0.0)
                popularity = details.get('popularity', 0.0)

                # Credits
                credits = details.get('credits', {})
                director = ''
                for crew in credits.get('crew', []):
                    if crew.get('job') == 'Director':
                        director = crew.get('name', '')
                        break

                #actors = [cast['name'] for cast in credits.get('cast', [])[:5]]
                
                videos = details.get('videos', {}).get('results', [])
                video_url = None
                for video in videos:
                    if video.get('site') == 'YouTube' and video.get('type') == 'Trailer':
                        # Prioriza oficial si existe
                        if video.get('official'):
                            key = video.get('key')
                            video_url = f"https://www.youtube.com/embed/{key}"
                            break
                        # O el primero que encuentres
                        elif not video_url:
                            key = video.get('key')
                            video_url = f"https://www.youtube.com/embed/{key}"
                            
                existing_movie = Movie.objects.filter(tmdb_id=tmdb_id).first()
                
                if existing_movie and existing_movie.embedding is not None:
                    self.stdout.write(self.style.NOTICE(f'Omitiendo Gemini para: {title} (Vector ya existe)'))
                    vector = existing_movie.embedding
                else:            
                    self.stdout.write(f'Generando vector multimodal para: {title}...')
                    full_poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
                    vector = generate_multimodal_embedding(overview, full_poster_url)
                    time.sleep(2)

                # Guardar o actualizar
                movie, created = Movie.objects.update_or_create(
                    tmdb_id=tmdb_id,
                    defaults={
                        'title': title,
                        'overview': overview,
                        'release_date': release_date,
                        'poster_path': poster_path,
                        'backdrop_path': backdrop_path,
                        'genres': genres,
                        'vote_average': vote_average,
                        'popularity': popularity,
                        'video_url': video_url,
                        'is_available': False,  # por ahora manual
                        'embedding': vector,
                    }
                )
                
                for cast in credits.get('cast', [])[:5]:
                    actor_name = cast.get('name')
                    if not actor_name:
                        continue

                    actor_tmdb_id = cast.get('id')  # TMDB ID del actor

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
                    self.stdout.write(self.style.SUCCESS(f'Creada: {title} (ID: {tmdb_id})'))
                else:
                    self.stdout.write(self.style.WARNING(f'Actualizada: {title}'))

                time.sleep(0.35) 

        self.stdout.write(self.style.SUCCESS('Populate completado!'))