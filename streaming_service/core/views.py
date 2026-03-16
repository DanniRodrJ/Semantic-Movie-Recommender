
from django.views.generic import list, detail, base
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib.auth import models, login, authenticate, logout
from django.contrib import messages
from .models import Movie
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q

class HomeView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'index.html'
    context_object_name = 'popular_movies'
    login_url = 'login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Secciones
        context['popular_movies']    = Movie.objects.order_by('-popularity')[:10]
        context['top_rated_movies']  = Movie.objects.order_by('-vote_average')[:10]
        context['recent_movies']     = Movie.objects.filter(release_date__isnull=False).order_by('-release_date')[:10]
        # Película destacada (la más popular o la última agregada)
        context['featured_movie']    = Movie.objects.order_by('-popularity').first()

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
    paginate_by = 20                            # paginación opcional

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
    slug_url_kwarg = 'slug'          # usamos slug en lugar de pk
    login_url = 'login'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        movie = self.object
        
        # ¿Está en favoritos del usuario actual?
        context['is_favorite'] = (
            self.request.user.is_authenticated and 
            movie in self.request.user.favorite_movies.all()
        )
        
        return context


class GenreListView(LoginRequiredMixin, list.ListView):
    model = Movie
    template_name = 'genre.html'
    context_object_name = 'movies'
    login_url = 'login'
    paginate_by = 20

    def get_queryset(self):
        genre = self.kwargs.get('genre').title()
        # Buscamos en el JSONField 'genres' (lista de dicts [{"id":.., "name":..}])
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
        if query:
            return Movie.objects.filter(
                Q(title__icontains=query) |
                Q(overview__icontains=query)
            ).distinct()
        return Movie.objects.none()

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

        return JsonResponse({'status': status, 'message': message})


class LoginView(base.TemplateView):
    template_name = 'login.html'

    def post(self, request, *args, **kwargs):
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('home')  # o 'index' si cambias el name
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

        login(request, user)
        return redirect('home')


class LogoutView(base.View):
    def get(self, request, *args, **kwargs):
        logout(request)
        return redirect('login')