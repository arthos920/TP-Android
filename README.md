Si nous avons déjà 5 jours de données, par exemple du 14 au 18 septembre, et que nous passons cette variable de 7 à 21, ces 5 jours restent conservés. Les prochaines collectes complètent progressivement l’historique jusqu’à atteindre 21 jours. Ensuite, chaque nouvelle journée remplace la plus ancienne.

Ce changement ne permet pas de récupérer les données antérieures au 14 septembre, ni celles déjà supprimées. Le script enregistre l’état des tests au moment de chaque collecte : il ne reconstitue pas leur état passé.
