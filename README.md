# Claimbridge
ClaimBridge is a review workspace for denied health-insurance claims. Five small agents (intake, retrieval, verifier, planner, curator) coordinate only through one FalkorDB graph, and the memory they learn carries a shelf life: a past win is used again only if its policy version, clause and conditions still apply.
