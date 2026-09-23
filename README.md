# Astuce Rouen (Transdev) – pour Home Assistant

Intégration Home Assistant qui affiche les **prochains passages des lignes
Transdev Rouen** du réseau Astuce (Métropole Rouen Normandie) aux arrêts de
votre choix, à partir de l'open data GTFS / GTFS-RT officiel publié sur
[transport.data.gouv.fr](https://transport.data.gouv.fr/datasets/donnees-statiques-et-temps-reel-du-reseau-astuce-metropole-rouen-normandie)
(licence Ouverte / Open Licence 2.0).

Fortement inspirée de [ha-tam-montpellier](https://github.com/3615nulsi/ha-tam-montpellier),
adaptée au réseau Astuce et volontairement limitée aux lignes exploitées par
**Transdev Rouen** : Metro, T1, T2, T3, T4, F1 à F8, Noctambus, 10, 11, 15,
20, 22, 27, 41 et 43.

> Projet indépendant, non affilié à la Métropole Rouen Normandie ni à
> Transdev Rouen. Code fourni sans garantie — voir la section
> [Limites connues](#limites-connues) avant de l'utiliser en production.

## Installation

### Manuelle

1. Copier `custom_components/astuce_rouen_transdev` dans le dossier
   `custom_components` de votre configuration Home Assistant.
2. Redémarrer Home Assistant.

### Avec HACS (dépôt personnalisé)

1. HACS → ⋮ → *Dépôts personnalisés*, ajouter l'URL de votre dépôt GitHub
   (type *Intégration*).
2. Installer **Astuce Rouen (Transdev)**, puis redémarrer Home Assistant.

## Configuration

1. *Paramètres → Appareils et services → Ajouter une intégration → Astuce
   Rouen (Transdev)*. Aucun champ n'est requis : l'intégration télécharge le
   GTFS Astuce au démarrage (quelques secondes, ~réseau entier filtré sur les
   lignes Transdev).
2. Sur la page de l'intégration, **Ajouter un arrêt** : choisir la ligne, la
   direction (destination), puis l'arrêt. Recommencer pour chaque arrêt à
   suivre. Un arrêt suivi peut être retiré depuis le même menu.

Chaque arrêt suivi devient un appareil (ex. « Théâtre des Arts → Georges
Braque (Metro) ») avec :

| Entité | Description |
| --- | --- |
| `sensor.…_minutes_avant_le_prochain_passage` | Minutes avant le prochain passage, **arrondies à l'inférieur** |
| `sensor.…_prochain_passage` | Heure exacte du prochain passage |
| `sensor.…_passage_suivant` | Heure exacte du passage d'après |
| `sensor.…_destination_du_prochain_passage` | Destination affichée par le prochain véhicule |
| `binary_sensor.…_perturbation` | Allumé si une alerte trafic en cours concerne la ligne, l'arrêt, ou tout le réseau |
| `sensor.…_message_de_perturbation` | Texte des alertes en cours (séparées par « • »), tronqué à 255 caractères (limite HA) ; texte complet dans l'attribut `full_message` |

Attributs du capteur minutes : `line`, `line_color`, `destination`, `delay`
(minutes), `source` (`realtime` / `estimated` / `scheduled`), et
`departures` (les prochains passages avec leurs minutes restantes).

## Exemples

### Tableau de départs (carte Markdown)

```yaml
type: markdown
content: >
  {% set s = 'sensor.theatre_des_arts_georges_braque_metro_minutes_avant_le_prochain_passage' %}
  ### {{ state_attr(s, 'line') }} · Théâtre des Arts
  Prochain : **{{ states('sensor.theatre_des_arts_georges_braque_metro_destination_du_prochain_passage') }}**
  {% for d in state_attr(s, 'departures') or [] %}
  - **{{ d.minutes }} min** → {{ d.destination }}
    {%- if d.source == 'scheduled' %} _(théorique)_{% endif %}
    {%- if d.delay %} · retard {{ d.delay }} min{% endif %}
  {% endfor %}
```

### Bandeau de perturbation (affiché seulement en cas d'alerte)

```yaml
type: conditional
conditions:
  - condition: state
    entity: binary_sensor.theatre_des_arts_georges_braque_metro_perturbation
    state: "on"
card:
  type: markdown
  content: >
    ⚠️ {{ state_attr('sensor.theatre_des_arts_georges_braque_metro_message_de_perturbation', 'full_message') }}
```

### « Il est temps de partir »

```yaml
triggers:
  - trigger: numeric_state
    entity_id: sensor.theatre_des_arts_georges_braque_metro_minutes_avant_le_prochain_passage
    below: 9
actions:
  - action: notify.mobile_app_mon_telephone
    data:
      message: >
        {{ state_attr(trigger.entity_id, 'line') }}
        dans {{ states(trigger.entity_id) }} min, c'est le moment de partir.
```

## Fonctionnement

- Le flux temps réel GTFS-RT `TripUpdate` des lignes Transdev Rouen est
  interrogé toutes les 30 secondes.
- Le flux GTFS-RT `Alert` (perturbations, réseau entier) est interrogé
  toutes les 60 secondes.
- Le GTFS théorique (arrêts, horaires, tracés — filtré aux seules lignes
  Transdev pour rester léger) est téléchargé au démarrage puis chaque nuit à
  3h30, et mis en cache dans `.storage/astuce_rouen_transdev_gtfs_static`.
- Si le flux temps réel ne couvre pas encore un passage (véhicule pas encore
  suivi, ou flux momentanément indisponible), l'horaire théorique est utilisé
  à la place (`scheduled`), éventuellement décalé du dernier retard connu sur
  la ligne (`estimated`) — comme pour TaM Montpellier.
- Si un flux est temporairement injoignable, les dernières données connues
  sont conservées plutôt que de rendre les capteurs indisponibles.

## Limites connues

Ce code a été écrit pour répondre précisément à votre besoin (lignes
Transdev Rouen + alertes) mais **n'a pas été testé sur une instance Home
Assistant réelle**. Avant de le considérer stable :

- Vérifiez dans les logs HA (`Paramètres → Système → Journaux`) qu'aucune
  erreur n'apparaît au chargement (`custom_components.astuce_rouen_transdev`).
- Le fichier `routes.txt` du GTFS Astuce doit bien exposer les noms courts de
  ligne listés dans `TRANSDEV_ROUTE_SHORT_NAMES` (`const.py`) — à ajuster si
  la nomenclature change.
- La position des véhicules (`vehicle_positions`) n'est pas implémentée
  (le flux officiel Transdev Rouen est d'ailleurs marqué indisponible sur le
  Point d'Accès National au moment de l'écriture).
- Pas encore de carte Lovelace façon « afficheur de quai » comme pour TaM —
  la carte Markdown ci-dessus suffit pour démarrer, un `button-card` dédié
  pourra être ajouté ensuite.

## Licence

Code sous licence [MIT](LICENSE). Projet indépendant, non affilié à
Transdev Rouen ni à la Métropole Rouen Normandie.

Données : © Métropole Rouen Normandie, licence
[Ouverte / Open Licence 2.0](https://www.etalab.gouv.fr/licence-ouverte-open-licence/).
