# Porte d'entrée Vercel

MediConnect est une application Django rendue côté serveur : le code tourne sur **Railway** (site + worker Celery +
Redis), la base est **MongoDB Atlas**. Ce dossier est un projet Vercel minimal qui sert de **porte d'entrée publique** :
il renvoie chaque requête vers le service Railway (réécriture `rewrites`), sur le réseau de Vercel (HTTPS, CDN).

Mise en place (une fois le service web Railway en ligne) :

1. Remplacer `RAILWAY_DOMAINE` dans `vercel.json` par le domaine public du service web Railway
   (ex. `mediconnect-web-production.up.railway.app`, sans `https://`).
2. Créer le projet Vercel avec **Root Directory = `deploiement/vercel`**, Framework Preset = **Other**, sans commande de build.
3. Sur Railway (service web), ajouter le domaine Vercel :
   - `DJANGO_ALLOWED_HOSTS` : `<domaine-railway>,<projet>.vercel.app`
   - `DJANGO_CSRF_TRUSTED_ORIGINS` : `https://<domaine-railway>,https://<projet>.vercel.app`
