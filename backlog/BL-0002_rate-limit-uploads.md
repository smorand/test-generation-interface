---
id: BL-0002
title: Aucune limitation de débit sur le dépôt, la saturation disque reste ouverte
kind: drift
origin: DRIFT-001 of SPEC-0001a
created: 2026-10-02
decision: Sébastien Morand, à la clôture de SPEC-0001a
---

## What

FR-NEW-006 borne un dépôt unique à 50 Mio, ce qui ferme l'écriture démesurée en un appel.
Cela ne ferme pas la saturation du disque : rien ne limite le **nombre** de dépôts, et un
attaquant non authentifié peut remplir le disque en répétant des dépôts de 50 Mio.

## Why

C'est la part `A:H` du vecteur CVSS de SPEC-0001a, que ce lot ne ferme donc qu'en partie.
Le risque résiduel est consigné en section 7.2 du document plutôt que passé sous silence,
mais il reste ouvert.

## Evidence

Recopié sans retouche depuis DRIFT-001 de SPEC-0001a. Les deux champs ci-dessous sont le
texte de l'entrée, mot pour mot ; la seule addition est la note de ligne entre crochets,
le code ayant bougé depuis que l'entrée a été écrite.

- **Code does:** la borne empêche un dépôt unique démesuré, mais rien ne limite le **nombre** de
  dépôts de 50 Mio. Il n'existe aucun compteur ni aucune limitation de débit dans le dépôt :
  `rg -n 'rate.?limit|slowapi|throttl' src/tgi/` ne rend rien, et la route de dépôt
  (`src/tgi/tgi.py:267-282`) n'en porte pas. De plus Starlette déverse le corps sur disque avant
  que le gestionnaire ne s'exécute, donc la borne de FR-NEW-006 agit **après** une écriture
  temporaire de la taille reçue.

[Note de relecture : la route de dépôt citée `src/tgi/tgi.py:267-282` se trouve désormais
aux environs de `src/tgi/tgi.py:330-350`, le fichier ayant grandi de la validation à la
frontière. La citation est conservée telle quelle, c'est celle de l'entrée d'origine.]

- **Detected by:** aucun test automatique ne mesure une saturation, et c'est dit plutôt que
  masqué. Le contrôle est documentaire : la section 7.2 porte un paragraphe
  « Risque résiduel assumé », dont la présence se vérifie à la relecture du gate. Cette entrée
  reste de nature A, et non promue en F, parce qu'aucun utilisateur ni consommateur de contrat
  n'observe de différence entre deux implémentations : seul le document change.

## Notes

À router par `/spec-feat` si une limitation de débit est retenue, le comportement
observable changeant pour un client légitime qui déposerait plusieurs documents de suite.
