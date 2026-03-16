import uuid
from django.db import models
from django.utils.dateparse import parse_date
from django.utils.text import slugify
from django.conf import settings

# Create your models here.

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
        verbose_name="Usuarios que la tienen como favorita"
    )
    is_available = models.BooleanField(default=False)
    actors = models.ManyToManyField(
        Actor,                       
        related_name='movies',        
        blank=True,
        verbose_name="Actores"
    )

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
            models.Index(fields=['title', 'release_date']),
        ]
        ordering = ['-popularity', '-vote_average', 'title']
        
        