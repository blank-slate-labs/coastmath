"""International tax regimes: the spec schema, registry, evaluator and pack rules.

Public modules: `types` (inputs, results, protocols), `spec` (`RegimeSpec`,
`AccountKindSpec`), `registry` (packs and rules), `evaluator` (`evaluate`,
`marginal_rate`) and `plugins` (rule registration). Pack data lives in
`coastmath/data/tax_regimes/<CC>/`; pack code in `coastmath/engine/intl/rules/<cc>.py`.
"""
