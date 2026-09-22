# Licensing and Data Provenance

[日本語](licensing_ja.md)

## Code and data are separate

The license at the repository root applies to EMS Material Manager code only. It does not automatically apply to material data, data extracted from publications, or data supplied by a customer.

The source code is distributed under PolyForm Perimeter License 1.0.1. See `LICENSE` and `NOTICE` in the repository root. Public users should read both files before using or redistributing the code.

## Dataset-level requirements

Every distributed material dataset must state:

- provider and primary source URL
- copyright notice and applicable license or terms of use
- retrieval date and dataset version
- whether commercial use, modification, and redistribution are allowed
- required attribution
- transformations made by EMSolution-SSIL, such as unit conversion or interpolation

The recommended placement is `data/<dataset>/README.md` for human-readable information and `data/<dataset>/manifest.json` for machine-readable provenance and file hashes.

## Third-party and public data

Public availability does not itself grant redistribution rights. Do not include IEEJ or other third-party material data in a public repository or package until its terms explicitly permit the intended redistribution. When redistribution is not permitted or unclear, distribute only an importer, source URL, and user instructions.

## Protected data

Contract, customer, and high-value datasets are not part of the public code repository. They are supplied separately under their own authorization and license terms. Encryption and key management do not replace a source-data license review.