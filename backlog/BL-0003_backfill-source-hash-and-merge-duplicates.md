---
id: BL-0003
title: Backfiller source_hash sur les projets existants et fusionner les doublons déjà créés
kind: idea
origin: YAGNI defer from SPEC-0002
created: 2026-10-03
---

## What

SPEC-0002 ajoute un dédoublonnage par hash de contenu (`source_hash`), mais uniquement pour
les créations **futures** (FR-NEW-015, DEC-006). Les projets déjà créés avant cette
fonctionnalité, y compris les trois doublons exacts visibles sur la capture d'écran jointe à
la demande d'origine ("0302 - SFD - Portefeuille et Intervenants _ v5"), ne sont ni
rétro-hashés ni fusionnés.

Cette entrée couvre, si elle est un jour reprise : un calcul de `source_hash` a posteriori
sur tout projet qui n'en porte pas, le regroupement des projets dont le hash coïncide, et une
décision explicite sur ce qu'il advient d'un projet doublon qui porte déjà des versions ou un
historique d'exécution (fusionner, archiver, ou laisser l'utilisateur choisir).

## Why

Rétro-fusionner des projets qui peuvent déjà porter des versions et des exécutions est une
opération nettement plus risquée que simplement arrêter de créer de nouveaux doublons : elle
implique une décision produit (que devient l'historique du doublon supprimé ?) que
SPEC-0002 n'a pas reçu mandat de prendre. La demande d'origine est formulée au futur
("ça évitera d'avoir plein de fois le même projet"), ce qui vise le flux à venir, pas le
nettoyage de l'existant.

## Notes

À router par `/spec-feat` si retenu : le comportement observable change pour tout projet
existant dont le hash validerait (possible disparition de la ligne dans la liste), ce qui
exige une décision utilisateur explicite sur le sort des versions du projet fusionné.
