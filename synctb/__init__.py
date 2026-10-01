"""synctb : synchronisation d'un tenant ThingsBoard PE depuis un dépôt de Version Control.

L'outil lit un dépôt git généré par le *Version Control* natif de ThingsBoard (déjà
cloné en local) et l'applique, via l'API REST, sur un tenant d'une instance en service.

Modules :
    cli      -- point d'entrée en ligne de commande (`synctb`)
    config   -- paramètres d'exécution (arguments + variables d'environnement)
    model    -- représentation en mémoire des fichiers du dépôt
    repo     -- lecture du dépôt Version Control
    filters  -- règles d'exclusion (utilisateurs, devices, assets non « Risque »)
    api      -- accès REST à l'instance cible (avec mode dry-run)
    specs    -- description REST de chaque type d'entité et ordres de traitement
    idmap    -- correspondance des identifiants source -> cible
    syncer   -- orchestration de la synchronisation
    report   -- compteurs et résumé final
"""

__version__ = "0.1.0"
