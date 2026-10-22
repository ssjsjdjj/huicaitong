"""Use explicit catalogue dates only; publication is not proof of legal effect."""


def available(policy, as_of, historical=False):
    if policy["published_on"] > as_of:
        return False
    if historical:
        return True
    return (policy["status"] == "included"
            and (not policy.get("effective_from") or policy["effective_from"] <= as_of)
            and (not policy.get("effective_until") or as_of <= policy["effective_until"]))
