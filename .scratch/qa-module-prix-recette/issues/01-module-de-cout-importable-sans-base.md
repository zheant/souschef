# 01 — Le module de coût s'importe et se teste sans base de données

**What to build:** Un développeur — ou un agent — peut importer le module pur de
calcul de prix et lancer ses tests dans un environnement sans SQLAlchemy ni
PostgreSQL, exactement comme la docstring du module et l'ADR le promettent
(« Ce module ne connaît ni SQLAlchemy ni HTTP », « les rapports hebdomadaires
peuvent comparer la couverture sans PostgreSQL »).

Aujourd'hui l'`__init__` du paquet `services` importe toute la couche d'un coup,
donc importer le module de coût tire SQLAlchemy et échoue si la dépendance est
absente. C'est un préfactoring : chaque ticket suivant livre des tests sur ce
module, et ils doivent pouvoir tourner sans base.

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `import` du module pur de coût, du module de vraisemblance et de l'audit de
      couverture réussit dans un interpréteur où SQLAlchemy n'est pas installé
- [ ] La façade SQL et les modules applicatifs existants s'importent toujours,
      sans changement pour leurs appelants
- [ ] La suite complète passe telle quelle (aucun test existant modifié pour
      accommoder le changement)
- [ ] Un test verrouille l'absence de dépendance : il échouerait si un import
      transitif vers SQLAlchemy revenait
