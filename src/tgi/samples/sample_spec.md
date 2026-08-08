# Spécification de validation, gestion des habilitations

Document synthétique servant à valider un modèle sur une infrastructure cible.
Il ne contient aucune donnée client. Il est calibré pour produire une vingtaine de
règles métier réparties sur trois sections, soit un volume représentatif d'un bloc
réel sans coûter une longue exécution.

## VAL01.CU01 Création d'une habilitation

VAL01.CU01.RM01 Le système crée une habilitation uniquement si le demandeur possède
le profil « gestionnaire » actif au moment de la demande.

VAL01.CU01.RM02 Une habilitation porte obligatoirement une date de début et une date
de fin, la date de fin devant être strictement postérieure à la date de début.

VAL01.CU01.RM03 Si la date de fin dépasse de plus de 24 mois la date de début, le
système rejette la demande et affiche le motif du rejet.

VAL01.CU01.RM04 Le système refuse la création d'une habilitation en doublon, une
habilitation étant considérée comme doublon si le triplet demandeur, périmètre et
période se recoupe avec une habilitation existante.

VAL01.CU01.RM05 Toute création d'habilitation est journalisée avec l'identifiant de
l'auteur, l'horodatage et le périmètre concerné.

Entrée : formulaire de demande contenant demandeur, périmètre, période.
Sortie : habilitation créée à l'état « en attente de validation ».

## VAL01.CU02 Validation et refus

VAL01.CU02.RM01 Une habilitation en attente doit être validée par un responsable
distinct du demandeur ; l'auto validation est interdite.

VAL01.CU02.RM02 Si le responsable refuse la demande, il doit saisir un motif d'au
moins 20 caractères, sans quoi le refus n'est pas enregistré.

VAL01.CU02.RM03 Une habilitation non traitée après 15 jours calendaires passe
automatiquement à l'état « expirée sans décision ».

VAL01.CU02.RM04 Le passage à l'état « expirée sans décision » déclenche une
notification au demandeur et à son responsable hiérarchique.

VAL01.CU02.RM05 Une habilitation validée devient active à sa date de début, et non
au moment de la validation.

| État | Transition autorisée | Acteur |
| --- | --- | --- |
| en attente | validée, refusée, expirée sans décision | responsable ou automate |
| validée | active, annulée | automate ou responsable |
| active | suspendue, clôturée | responsable |
| refusée | aucune | aucun |

## VAL01.CU03 Suspension et clôture

VAL01.CU03.RM01 Le système suspend automatiquement toutes les habilitations actives
d'une personne dont le contrat est marqué comme rompu dans le référentiel RH.

VAL01.CU03.RM02 Une habilitation suspendue peut être réactivée dans les 30 jours,
au delà elle est clôturée définitivement.

VAL01.CU03.RM03 La clôture d'une habilitation conserve l'historique complet et
interdit toute modification ultérieure.

VAL01.CU03.RM04 Chaque nuit, le système clôture les habilitations dont la date de
fin est dépassée depuis plus d'un jour.

VAL01.CU03.RM05 Un traitement de clôture qui échoue est rejoué au maximum trois
fois, puis signalé dans le rapport d'exploitation quotidien.

VAL01.CU03.RM06 Le rapport d'exploitation quotidien liste le nombre
d'habilitations créées, validées, refusées, suspendues et clôturées sur la journée.
