from django.urls import path
from . import views

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('signup/', views.SignupView.as_view(), name='signup'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('onboarding/', views.OnboardingView.as_view(), name='onboarding'),
    path('movie/<slug:slug>/', views.MovieDetailView.as_view(), name='movie_detail'),
    path('popular/', views.PopularMoviesView.as_view(), name='popular_all'),
    path('personalized/', views.PersonalizedMoviesView.as_view(), name='personalized_all'),
    path('genre/<str:genre>/', views.GenreListView.as_view(), name='genre'),
    path('search/', views.SearchView.as_view(), name='search'),
    path('my_list', views.MyListView.as_view(), name='my_list'),
    path('toggle_favorite/', views.ToggleFavoriteView.as_view(), name='toggle_favorite'),
    path('record_watch/', views.RecordWatchView.as_view(), name='record_watch'),
    path('feedback/', views.FeedbackView.as_view(), name='movie_feedback'),
]
