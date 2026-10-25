"""Structure the model catalog by role and tier without UI or install actions.

One model may belong to several roles. This describes its presentation only;
selection and install/remove state continue to be keyed by the unique tag.
"""


def group_catalog(catalog):
    """Return role groups with their primary and optional models, plus unassigned models."""
    by_tag = {entry['tag']: entry for entry in catalog['models']}
    assigned = set()
    groups = []
    for role in catalog.get('role_tiers', ()):
        tiers = []
        seen_options = set()
        for tier in role.get('tiers', ()):
            primary = by_tag.get(tier['primary'])
            if primary is not None:
                assigned.add(primary['tag'])
            options = []
            for tag in tier.get('alts', ()):
                entry = by_tag.get(tag)
                if entry is None or tag == tier['primary'] or tag in seen_options:
                    continue
                options.append(entry)
                seen_options.add(tag)
                assigned.add(tag)
            tiers.append({
                'number': tier['number'],
                'level_label': tier['level_label'],
                'recommended': primary,
                'options': options,
            })
        groups.append({
            'key': role['key'],
            'title': role['title'],
            'desc': role.get('desc', ''),
            'tiers': tiers,
            'optional_count': sum(len(tier['options']) for tier in tiers),
        })
    return {
        'roles': groups,
        'extra': [entry for entry in catalog['models']
                  if entry['tag'] not in assigned],
    }
