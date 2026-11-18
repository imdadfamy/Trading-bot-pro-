# Annonces américaines et fenêtres de prudence

## À quoi ça sert

Autour de certaines publications américaines, l'or bouge très vite et l'écart achat-vente s'élargit. Pendant une **fenêtre de prudence** autour de ces annonces, le système **n'autorise aucune nouvelle entrée** : le cycle de recherche répond « attente » avec la raison précise, et le contrôle de risque refuse tout signal. Aucune dépense : les dates viennent des calendriers officiels, publics et publiés à l'avance. Le calendrier économique payant n'est pas utilisé.

## Ce qui est couvert

| Annonce | Source officielle | Heure | Fenêtre (avant / après) |
| --- | --- | --- | --- |
| Emploi américain (NFP) | BLS, « Employment Situation » | 08:30 heure de l'Est | 30 min / 60 min |
| Inflation américaine (CPI) | BLS, « Consumer Price Index » | 08:30 heure de l'Est | 30 min / 60 min |
| Prix à la production (PPI) | BLS, « Producer Price Index » | 08:30 heure de l'Est | 15 min / 30 min |
| Décision de la Réserve fédérale (FOMC) | Calendrier de la Réserve fédérale | 14:00 heure de l'Est (conférence de presse ensuite) | 30 min / 90 min |

Les dates sont dans `config/us_events.json` : 2026 complet et 2027 complet pour l'emploi, l'inflation et les prix à la production, et les réunions de la Réserve fédérale jusqu'au 26 janvier 2028. Relevé initial le 18 novembre 2026. Les fenêtres se règlent dans le même fichier (clé `windows`). Les heures sont converties en UTC avec la règle d'heure d'été américaine.

## Ce qui n'est pas couvert

Les annonces **imprévues** (déclaration d'urgence, choc politique) ne figurent dans aucun calendrier, même payant. Elles sont couvertes par d'autres protections, qui ne sont pas parfaites :
1. une actualité jugée critique suspend les entrées ;
2. la limite d'écart refuse d'entrer quand l'écart explose ;
3. un cours périmé bloque les entrées.

D'autres publications (ventes au détail, PCE, PIB, demandes d'allocations chômage) ne sont pas dans la liste.

## Qui met le calendrier à jour ?

Personne chaque jour : les dates sont connues des mois à l'avance. L'application affiche une alerte dans la rubrique **Sessions** quand une série expire dans moins de 30 jours ou est périmée. Aujourd'hui, la série la plus courte va jusqu'au 3 décembre 2027.

- **Réserve fédérale : entièrement automatique.** Une commande lit la page officielle (une seule requête) et met à jour les décisions :

```powershell
Set-Location -LiteralPath 'C:\Users\imdad\TRADING bot pro\backend'
python -m trading_pro.cli refresh-us-events --fed --dry-run   # voir ce qui changerait, sans écrire
python -m trading_pro.cli refresh-us-events --fed
```

- **BLS (emploi, inflation, prix à la production)** : le site refuse les téléchargements par programme (erreur 403) et l'application ne contourne pas ce refus. Télécharger une fois le fichier officiel `https://www.bls.gov/schedule/news_release/bls.ics` dans un navigateur, puis :

```powershell
python -m trading_pro.cli refresh-us-events --bls-ics C:\chemin\vers\bls.ics --dry-run
python -m trading_pro.cli refresh-us-events --bls-ics C:\chemin\vers\bls.ics
```

  Ce fichier ne contient que l'année en cours ; les pages de calendrier du BLS donnent aussi l'année suivante. Une mise à jour n'écrit rien si le résultat est invalide, et remplace uniquement les dates à partir de la première date reçue.

## Vérifier à tout moment

```powershell
python -m trading_pro.cli us-events                                   # prochaines annonces et validité
python -m trading_pro.cli us-events --at 2026-12-04T13:45:00+00:00    # simuler une date
```

L'API expose la même chose sur `GET /announcements`. Les cycles de recherche (`cycle`, `analyze-with-models`) appliquent la fenêtre à l'heure de la dernière bougie ; hors des dates couvertes, ils n'inventent aucune fenêtre. Le futur programme d'exécution devra appeler la version « stricte » qui, elle, suspend les entrées si le calendrier est absent ou périmé.
