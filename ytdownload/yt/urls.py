from django.urls import path
from . import views

urlpatterns=[
  path('',views.index,name='index'),
  path('download/<uuid:ticket_id>/', views.DeleteAfterStreamFileResponse, name='deletestreamfile'),
   path('done/', views.done, name='done'),
]