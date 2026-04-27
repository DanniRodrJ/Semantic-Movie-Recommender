import uuid, numpy as np
from django.db import models
from pgvector.django import VectorField, HnswIndex
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.conf import settings

class Actor(models.Model):
    name = models.CharField(max_length=255, db_index=True)
    tmdb_id = models.PositiveIntegerField(unique=True, null=True, blank=True)  # opcional, pero útil
    profile_path = models.CharField(max_length=255, blank=True, null=True)     # para foto
    popularity = models.FloatField(default=0.0, blank=True)                    # de TMDB

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['-popularity', 'name']
        
class Movie(models.Model):
    tmdb_id = models.PositiveIntegerField(unique=True, null=True, blank=True)
    title = models.CharField(max_length=255, db_index=True)
    runtime = models.IntegerField(null=True, blank=True, help_text="Runtime in minutes")
    slug = models.SlugField(max_length=255, unique=True, blank=True, null=True)
    overview = models.TextField(blank=True)
    release_date = models.DateField(null=True, blank=True)
    poster_path = models.CharField(max_length=255, blank=True, null=True)
    backdrop_path = models.CharField(max_length=255, blank=True, null=True)
    genres = models.JSONField(default=list, blank=True) 
    vote_average = models.FloatField(default=0.0)
    popularity = models.FloatField(default=0.0)
    video_url = models.URLField(blank=True, null=True)
    favorites = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='favorite_movies',
        blank=True,
        verbose_name="Users who have bookmarked it"
    )
    is_available = models.BooleanField(default=True)
    actors = models.ManyToManyField(
        Actor,                       
        related_name='movies',        
        blank=True,
        verbose_name="Actores"
    )
    director = models.CharField(max_length=255, null=True, blank=True)
    embedding = VectorField(dimensions=768, null=True, blank=True)  # The film's multimodal approach
    embedding_tokens = models.IntegerField(default=0, help_text="Tokens spent on Gemini", null=True, blank=True)
    
    def __str__(self):
        return self.title
    
    @property
    def poster_url(self):
        if self.poster_path:
            return f"https://image.tmdb.org/t/p/w500{self.poster_path}"
        return ""  # fallback
    
    @property
    def backdrop_url(self):
        if self.backdrop_path:
            return f"https://image.tmdb.org/t/p/original{self.backdrop_path}"
        return ""
    
    def save(self, *args, **kwargs):
        if not self.slug and self.title:  
            base_slug = slugify(self.title)
            
            year = None
            if self.release_date:
                if isinstance(self.release_date, str):
                    parsed = parse_date(self.release_date)
                    if parsed:
                        year = parsed.year
                else:  # ya es date
                    year = self.release_date.year
            
            if year:
                base_slug = slugify(f"{self.title} {year}")
            self.slug = base_slug
            
            original_slug = self.slug
            counter = 1
            while Movie.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{original_slug}-{counter}"
                counter += 1
        
        super().save(*args, **kwargs)
        
    class Meta:
        indexes = [
            HnswIndex(
                name='movie_embed_hnsw_idx',
                fields=['embedding'],
                m=16,                # Number of bidirectional connections in the graph
                ef_construction=64,  # Size of the dynamic list during construction
                opclasses=['vector_cosine_ops'] 
            )
        ]
        ordering = ['-popularity', '-vote_average', 'title']
        
class UserProfile(models.Model):
    
    AVATAR_CHOICES = [
        ('bottts', 'AI Robot'),
        ('identicon', 'Geometric Pattern'),
        ('pixel-art', 'Pixel Art'),
        ('shapes', 'Abstract Forms'),
    ]
    
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    preference_vector = VectorField(dimensions=768, null=True, blank=True)
    preference_tokens = models.IntegerField(default=0, help_text="Tokens spent on Gemini")
    has_completed_onboarding = models.BooleanField(default=False)
    avatar_style = models.CharField(max_length=20, choices=AVATAR_CHOICES, default='bottts')
    disliked_movies = models.ManyToManyField('Movie', related_name='disliked_by', blank=True)
    
    def __str__(self):
        return f"Profile of {self.user.username}"
    
    @property
    def avatar_url(self):
        return f"https://api.dicebear.com/7.x/{self.avatar_style}/svg?seed={self.user.username}"

    def update_preference_vector(self):
        """Calculate the centroid by combining Favorites (+2), History (+0.5) and Dislikes (-0.5)"""
        vectors = []
        weights = []

        # 1. Favorites
        fav_movies = self.user.favorite_movies.filter(embedding__isnull=False)
        fav_ids = set()
        for movie in fav_movies:
            vectors.append(np.array(movie.embedding))
            weights.append(2.0) # Double Weight
            fav_ids.add(movie.id)

        # 2. History (limit to the last 50 to not drag old tastes)
        history = WatchHistory.objects.filter(
            user=self.user, 
            movie__embedding__isnull=False
        ).select_related('movie').order_by('-watched_at')[:50]

        history_ids = set()
        for item in history:
            # Only add if not in favorites (to avoid duplicate calculations)
            if item.movie.id not in fav_ids:
                vectors.append(np.array(item.movie.embedding))
                weights.append(0.5) # Half weight
                history_ids.add(item.movie.id)
                
        has_positive_anchors = len(vectors) > 0
                
        # 3. Dislikes
        if has_positive_anchors:
            dislikes = self.disliked_movies.filter(embedding__isnull=False)
            for movie in dislikes:
                vectors.append(np.array(movie.embedding))
                weights.append(-0.5)

        # 3. Vector math
        if vectors:
            weighted_sum = np.zeros(768)
            total_weight_abs = 0.0
            
            for v, w in zip(vectors, weights):
                weighted_sum += v * w
                total_weight_abs += abs(w)
                
            if total_weight_abs > 0:
                centroid = weighted_sum / total_weight_abs
                
                norm = np.linalg.norm(centroid)
                if norm > 0:
                    centroid = centroid / norm
                    
                self.preference_vector = centroid.tolist()
            else:
                self.preference_vector = None
        else:
            self.preference_vector = None
            
        self.save()


class WatchHistory(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE)
    watched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-watched_at']       
        
        
        
class SearchAnalytics(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    query = models.CharField(max_length=500)
    latency_ms = models.FloatField(help_text="Execution time in milliseconds")
    tokens_used = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0.0)
    results_count = models.IntegerField(default=0)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = "Search Analytics"

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {self.query} ({self.latency_ms}ms)"
    
    
class PipelineAnalytics(models.Model):
    task_name = models.CharField(max_length=255, default="fetch_and_vectorize_movies")
    movies_processed = models.IntegerField(default=0)
    total_tokens_used = models.IntegerField(default=0)
    estimated_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0.0)
    execution_time_seconds = models.FloatField(help_text="Total duration of the script")
    status = models.CharField(max_length=50, default="Success")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name_plural = "Pipeline Analytics"

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {self.movies_processed} movies | Cost: ${self.estimated_cost_usd}"