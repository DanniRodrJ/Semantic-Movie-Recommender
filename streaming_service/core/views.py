
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
        context['featured_movie']    = Movie.objects.order_by('-popularity').first()

        # Personalized recommendations
        if hasattr(self.request.user, 'profile') and self.request.user.profile.preference_vector:
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
            print(f"DEBUG: {genre} → {count} películas")    
        
        context['genre_sections'] = genre_sections
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
        context['title'] = 'Todas las películas populares'
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


class SearchView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'search.html'
    context_object_name = 'movies'
    login_url = 'login'

    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()
        if not query:
            return Movie.objects.none()
        
        # LEXICAL SEARCH
        lexical_results = list(Movie.objects.filter(title__icontains=query))

        # SEMANTIC SEARCH
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
            )[:12]

            semantic_results = list(semantic_qs)

        # HYBRID MERGER
        final_movies = lexical_results.copy()
        for movie in semantic_results:
            if movie not in final_movies:
                final_movies.append(movie)

        return final_movies

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
            message = 'Eliminada ✓'
        else:
            request.user.favorite_movies.add(movie)
            status = 'added'
            message = 'Agregada ✓'

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
            messages.error(request, 'Credenciales inválidas')
            return redirect('login')


class SignupView(base.TemplateView):
    template_name = 'signup.html'

    def post(self, request, *args, **kwargs):
        email = request.POST.get('email')
        username = request.POST.get('username')
        password = request.POST.get('password')
        password2 = request.POST.get('password2')

        if password != password2:
            messages.error(request, 'Las contraseñas no coinciden')
            return redirect('signup')

        if models.User.objects.filter(email=email).exists():
            messages.error(request, 'El email ya está en uso')
            return redirect('signup')

        if models.User.objects.filter(username=username).exists():
            messages.error(request, 'El usuario ya existe')
            return redirect('signup')

        user = models.User.objects.create_user(username=username, email=email, password=password)
        user.save()

        # Blank vector outline
        UserProfile.objects.create(user=user)

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