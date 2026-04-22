
import json, numpy as np
import logging
from django.views.generic import list, detail, base
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib.auth import models, login, authenticate, logout
from django.contrib import messages
from .models import Movie, UserProfile, WatchHistory
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q
from pgvector.django import CosineDistance
from .services import generate_multimodal_embedding
from .utils import measure_hybrid_search

logger = logging.getLogger(__name__)

class HomeView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'index.html'
    context_object_name = 'popular_movies'
    login_url = 'login'

    def dispatch(self, request, *args, **kwargs):
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        if not profile.has_completed_onboarding:
            return redirect('onboarding')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        context['popular_movies']    = Movie.objects.order_by('-popularity')[:10]
        context['top_rated_movies']  = Movie.objects.order_by('-vote_average')[:10]
        context['recent_movies']     = Movie.objects.filter(release_date__isnull=False).order_by('-release_date')[:10]
        
        if hasattr(self.request.user, 'profile') and self.request.user.profile.preference_vector is not None:
            user_vector = self.request.user.profile.preference_vector
            
            qs_personalized = Movie.objects.filter(
                embedding__isnull=False, vote_average__gte=6.5
            ).order_by(CosineDistance('embedding', user_vector))[:3]
            hero_personalized = [m for m in qs_personalized]
            
            hero_ids = [m.id for m in hero_personalized]
            
            qs_exploration = Movie.objects.exclude(id__in=hero_ids).order_by('?')[:2]
            hero_exploration = [m for m in qs_exploration]
            
            featured_movies = []
            if len(hero_personalized) == 3 and len(hero_exploration) == 2:
                featured_movies = [hero_personalized[0], hero_exploration[0], hero_personalized[1], hero_exploration[1], hero_personalized[2]]
            else:
                featured_movies = hero_personalized + hero_exploration
                
            final_hero_ids = [m.id for m in featured_movies]
            context['featured_movies'] = featured_movies
            
            context['personalized_movies'] = Movie.objects.filter(
                embedding__isnull=False
            ).exclude(id__in=final_hero_ids).order_by(
                CosineDistance('embedding', user_vector)
            )[:15]
        else:
            context['featured_movie']    = Movie.objects.order_by('-popularity').first()

        # Personalized recommendations
        if hasattr(self.request.user, 'profile') and self.request.user.profile.preference_vector is not None:
            personalized = Movie.objects.filter(
                embedding__isnull=False
            ).order_by(
                CosineDistance('embedding', self.request.user.profile.preference_vector)
            )[:15] # Top 15 most similar movies to the user's preferences
            context['personalized_movies'] = personalized
        
        genres_to_show = ['Action', 'Comedy', 'Drama', 'Horror', 'Romance', 'Science Fiction', 'Thriller']
        genre_sections = {}
        for genre in genres_to_show:
            movies = Movie.objects.filter(genres__contains=[{'name': genre}]).order_by('-popularity')[:10]
            if movies.exists():
                genre_sections[genre] = movies
                
            count = movies.count()
            logger.debug(f"{genre} → {count} movies found.")    
        
        context['genre_sections'] = genre_sections
        
        history_records = WatchHistory.objects.filter(user=self.request.user).select_related('movie').order_by('-watched_at')
        continue_watching = []
        seen_ids = set()
        
        for record in history_records:
            if record.movie.id not in seen_ids:
                continue_watching.append(record.movie)
                seen_ids.add(record.movie.id)
            if len(continue_watching) == 10: # Limit to the 10 most recent unique movies
                break
                
        context['continue_watching'] = continue_watching
        
        return context
    
    
class PersonalizedMoviesView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'popular_all.html' 
    context_object_name = 'movies'
    login_url = 'login'
    paginate_by = 20

    def get_queryset(self):
        if hasattr(self.request.user, 'profile') and self.request.user.profile.preference_vector is not None:
            return Movie.objects.filter(embedding__isnull=False).order_by(
                CosineDistance('embedding', self.request.user.profile.preference_vector)
            )
        return Movie.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = '✨ Recommended for you'
        return context
    

class PopularMoviesView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'popular_all.html'          
    context_object_name = 'movies'
    login_url = 'login'
    paginate_by = 20

    def get_queryset(self):
        return Movie.objects.order_by('-popularity')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = '🔥 Most Popular Movies'
        return context


class MovieDetailView(LoginRequiredMixin, detail.DetailView):
    model = Movie
    template_name = 'movie.html'
    context_object_name = 'movie'
    slug_url_kwarg = 'slug'          
    login_url = 'login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movie = self.object
        
        # Is it in the current user's favorites?
        context['is_favorite'] = (
            self.request.user.is_authenticated and 
            movie in self.request.user.favorite_movies.all()
        )

        # MULTIMODAL RECOMMENDATION ENGINE (Cosine Similarity)
        if movie.embedding is not None:
            # Search the database for movies with the most similar vector
            similar_movies = Movie.objects.filter(
                embedding__isnull=False
            ).exclude(
                id=movie.id
            ).order_by(
                CosineDistance('embedding', movie.embedding)
            )[:6]

            context['similar_movies'] = similar_movies
        else:
            context['similar_movies'] = []
           
        return context


class GenreListView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'genre.html'
    context_object_name = 'movies'
    login_url = 'login'
    paginate_by = 20

    def get_queryset(self):
        genre = self.kwargs.get('genre').title()
        return Movie.objects.filter(
            genres__contains=[{'name': genre}]
        ).distinct().order_by('-popularity')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['movie_genre'] = self.kwargs.get('genre').title()
        return context



@measure_hybrid_search
def execute_rrf_search(query, user=None):
    # LEXICAL SEARCH
    qs_lexical = Movie.objects.filter(title__icontains=query)
    lexical_results = [m for m in qs_lexical]

    # SEMANTIC SEARCH (Embeddings)
    semantic_results = []
    vector, _ = generate_multimodal_embedding(
        text_overview=query, 
        image_url=None, 
        task_type="RETRIEVAL_QUERY"
    )

    if vector:
        semantic_qs = Movie.objects.filter(
            embedding__isnull=False
        ).order_by(
            CosineDistance('embedding', vector)
        )[:20]
        semantic_results = [m for m in semantic_qs]
        
    # RECIPROCAL RANK FUSION (RRF) score = 1 / (k + rank)
    rrf_scores = {}
    k = 60
    
    # Score lexical results 
    for rank, movie in enumerate(lexical_results):
        if movie.id not in rrf_scores:
            rrf_scores[movie.id] = {'movie': movie, 'score': 0.0}
        rrf_scores[movie.id]['score'] += 1.0 / (k + rank + 1)
        
    # Score semantic results
    for rank, movie in enumerate(semantic_results):
        if movie.id not in rrf_scores:
            rrf_scores[movie.id] = {'movie': movie, 'score': 0.0}
        rrf_scores[movie.id]['score'] += 1.0 / (k + rank + 1)

    sorted_rrf = sorted(rrf_scores.values(), key=lambda x: x['score'], reverse=True)
    final_movies = [item['movie'] for item in sorted_rrf][:15]
    
    return final_movies, query

class SearchView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'search.html'
    context_object_name = 'movies'
    login_url = 'login'

    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()
        if not query:
            return Movie.objects.none()
        
        movies, _ = execute_rrf_search(query=query, user=self.request.user)
        return movies

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_term'] = self.request.GET.get('q', '')
        return context


class MyListView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'my_list.html'
    context_object_name = 'movies'
    login_url = 'login'

    def get_queryset(self):
        return self.request.user.favorite_movies.order_by('-popularity')


class ToggleFavoriteView(LoginRequiredMixin, base.View):
    login_url = 'login'

    def post(self, request, *args, **kwargs):
        movie_slug = request.POST.get('movie_slug')
        movie = get_object_or_404(Movie, slug=movie_slug)

        if movie in request.user.favorite_movies.all():
            request.user.favorite_movies.remove(movie)
            status = 'removed'
            message = 'Removed ✓'
        else:
            request.user.favorite_movies.add(movie)
            status = 'added'
            message = 'Added ✓'

        # Update preference vector
        if hasattr(request.user, 'profile'):
            request.user.profile.update_preference_vector()

        return JsonResponse({'status': status, 'message': message})


class RecordWatchView(LoginRequiredMixin, base.View):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            movie_id = data.get('movie_id')
            movie = get_object_or_404(Movie, id=movie_id)
            
            # Save watch history
            WatchHistory.objects.create(user=request.user, movie=movie)
            
            # Recalculate vector
            if hasattr(request.user, 'profile'):
                request.user.profile.update_preference_vector()
                
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


class LoginView(base.TemplateView):
    template_name = 'login.html'

    def post(self, request, *args, **kwargs):
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            messages.error(request, 'Invalid username or password')
            return redirect('login')


class SignupView(base.TemplateView):
    template_name = 'signup.html'

    def post(self, request, *args, **kwargs):
        email = request.POST.get('email')
        username = request.POST.get('username')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')

        if password != password2:
            messages.error(request, 'The passwords do not match')
            return redirect('signup')

        if models.User.objects.filter(email=email).exists():
            messages.error(request, 'The email is already in use')
            return redirect('signup')

        if models.User.objects.filter(username=username).exists():
            messages.error(request, 'The username is already in use')
            return redirect('signup')

        user = models.User.objects.create_user(username=username, email=email, password=password)
        user.save()
        
        avatar_style = request.POST.get('avatar_style', 'bottts')

        # Blank vector outline
        UserProfile.objects.create(user=user, avatar_style=avatar_style)

        login(request, user)
        return redirect('onboarding')


class OnboardingView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'onboarding.html'
    context_object_name = 'movies'
    login_url = 'login'

    def get_queryset(self):
        return Movie.objects.filter(embedding__isnull=False).order_by('?')[:40]

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            action = data.get('action', 'submit')

            profile, _ = UserProfile.objects.get_or_create(user=request.user)
            if action == 'skip':
                profile.has_completed_onboarding = True
                profile.save()
                return JsonResponse({'status': 'success', 'redirect': '/'})

            selected_ids = data.get('movie_ids', [])
            if len(selected_ids) > 0:
                selected_movies = Movie.objects.filter(id__in=selected_ids, embedding__isnull=False)
                vectors = [np.array(movie.embedding) for movie in selected_movies]

                if vectors:
                    # The centroid (average of the vectors) is calculated
                    centroid = np.mean(vectors, axis=0)

                    # The user's profile is updated with the centroid
                    profile, _ = UserProfile.objects.get_or_create(user=request.user)
                    profile.preference_vector = centroid.tolist()
                    profile.has_completed_onboarding = True
                    profile.save()

                    return JsonResponse({'status': 'success', 'redirect': '/'})
            return JsonResponse({'status': 'error', 'message': 'No movies selected'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

class LogoutView(base.View):
    def get(self, request, *args, **kwargs):
        logout(request)
        return redirect('login')