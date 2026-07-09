from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('stream/<uuid:ticket_id>/', views.stream_download, name='deletestreamfile'),
    path('done/', views.done, name='done'),
]