"""Conservative recommendations for existing identifiers; Shopware owns roles."""
from core.services import BaseService

BUSINESS_FIELDS = ('company', 'name1', 'name2', 'name3', 'department', 'street',
                   'postal_code', 'city', 'country_code', 'email', 'title',
                   'first_name', 'last_name', 'phone')


def clean(value):
    return ' '.join(str(value or '').split()).casefold()


def microtech_company(fields):
    # Microtech often stores 'Firma' in Na1 and the company itself in Na2.
    return next((clean(fields.get(k)) for k in ('name1', 'name2', 'name3')
                 if clean(fields.get(k)) and clean(fields.get(k)) not in ('firma', 'herr', 'frau')), '')


def identical_addresses(left, right):
    return (all(clean(left.get(k)) for k in ('street', 'postal_code', 'city'))
            and any(clean(left.get(k)) for k in ('company', 'name1', 'first_name', 'last_name'))
            and all(clean(left.get(k)) == clean(right.get(k)) for k in BUSINESS_FIELDS))


class AddressRecommendationService(BaseService):
    """Suggest only unambiguous existing matches, without reading or writing I/O."""

    @staticmethod
    def proposals(snapshot):
        records = snapshot['records']
        operations, evidence = [], []
        projected = {r['ref']: dict(r['fields']) for r in records}
        def add(kind, source, target, reason):
            operations.append(dict(kind=kind, source=source['ref'], target=target['ref'], reason=reason))
            field = next(k for k in ('street', 'contactNumber', 'addressSubNumber', 'id') if k in source['fields'])
            evidence.append(dict(ref=source['ref'], field=field, finding=reason))
        for customer in (r for r in records if r['system'] == 'sw' and r['kind'] == 'customer'):
            number = customer['number']
            local = next((r for r in records if r['system'] == 'dj' and r['kind'] == 'customer' and r['number'] == number), None)
            if not local:
                continue
            if not local['fields'].get('api_id'):
                add('link_customer', customer, local, 'Vorhandenes Shopkonto zuordnen.')
            elif clean(local['fields']['api_id']) != clean(customer['fields']['id']):
                continue
            addresses = [r for r in records if r['system'] == 'dj' and r['kind'] == 'address' and r['parent'] == local['ref']]
            shops = [r for r in records if r['system'] == 'sw' and r['kind'] == 'address' and r['parent'] == customer['ref']]
            defaults = {customer['fields'].get(k) for k in ('defaultBillingAddressId', 'defaultShippingAddressId')}
            # Selected Shopware records take precedence over identical spare rows.
            addresses.sort(key=lambda r: (r['fields'].get('api_id') not in defaults, r['ref']))
            for address in addresses:
                f = projected[address['ref']]
                shop = next((r for r in shops if clean(r['fields']['id']) == clean(f.get('api_id'))), None)
                if not shop and not f.get('api_id'):
                    matches = [r for r in shops if all(clean(f.get(a)) == clean(r['fields'].get(b)) and clean(f.get(a))
                        for a, b in [('street','street'),('postal_code','zipcode'),('city','city'),('first_name','firstName'),('last_name','lastName')])
                        and clean(f.get('company')) == clean(r['fields'].get('company'))
                        and not any(clean(x.get('api_id')) == clean(r['fields']['id']) for x in projected.values())]
                    if len(matches) == 1:
                        shop = matches[0]; f['api_id'] = shop['fields']['id']
                        add('link_shopware_address', shop, address, 'Vorhandene Anschrift und Person stimmen überein.')
                if not shop:
                    continue
                # A matching ID alone does not prove unchanged business fields.
                if any(not clean(f.get(a)) or clean(f.get(a)) != clean(shop['fields'].get(b))
                       for a,b in [('street','street'),('postal_code','zipcode'),('city','city'),('first_name','firstName'),('last_name','lastName')]):
                    continue
                if clean(f.get('company')) != clean(shop['fields'].get('company')):
                    continue
                is_standard = shop['fields']['id'] in defaults
                if not is_standard and any(other['ref'] != address['ref'] and other['fields'].get('api_id') in defaults
                                           and identical_addresses(f, other['fields']) for other in addresses):
                    continue
                current_mt = next((r for r in records if r['system']=='mt' and r['kind']=='address' and r['number']==number and r['fields'].get('addressSubNumber')==f.get('erp_ans_nr')), None)
                current_matches = current_mt and all(clean(f.get(a)) == clean(current_mt['fields'].get(b))
                    for a,b in [('street','street'),('postal_code','zipCode'),('city','city')])
                if not current_matches:
                    matches = [r for r in records if r['system'] == 'mt' and r['kind'] == 'address' and r['number'] == number
                        and all(clean(f.get(a)) == clean(r['fields'].get(b)) and clean(f.get(a))
                                for a, b in [('street','street'),('postal_code','zipCode'),('city','city')])
                        and clean(f.get('company') or f.get('name1')) == microtech_company(r['fields'])
                        and (not r['fields'].get('country') or clean(f.get('country_code')) == clean(r['fields']['country']))
                        and clean(f.get('department')) == clean(r['fields'].get('department'))]
                    if len(matches) == 1:
                        mt = matches[0]
                        contacts = [r for r in records if r['kind'] == 'contact' and r['parent'] == mt['ref']]
                        person = [r for r in contacts if all(clean(f.get(a)) and clean(f.get(a)) == clean(r['fields'].get(b))
                                  for a,b in [('first_name','firstName'),('last_name','lastName')])]
                        source = person[0] if len(person) == 1 else mt if not contacts else None
                        if source:
                            ans, asp = mt['fields']['addressSubNumber'], source['fields'].get('contactNumber')
                            collisions = [r for r in addresses if r['ref'] != address['ref'] and projected[r['ref']].get('erp_ans_nr') == ans and projected[r['ref']].get('erp_asp_nr') == asp]
                            if all(identical_addresses(f, r['fields']) for r in collisions):
                                f.update(erp_ans_nr=ans, erp_asp_nr=asp)
                                add('link_microtech_address', source, address, 'Passende vorhandene Microtech-Anschrift und Person zuordnen.')
                for role, swfield, djfield, mtfield in [('set_billing','defaultBillingAddressId','is_invoice','isDefaultBilling'),('set_shipping','defaultShippingAddressId','is_shipping','isDefaultShipping')]:
                    if shop['fields']['id'] != customer['fields'].get(swfield) or f.get('erp_ans_nr') is None:
                        continue
                    mt = next((r for r in records if r['system'] == 'mt' and r['kind'] == 'address' and r['number'] == number and r['fields'].get('addressSubNumber') == f['erp_ans_nr']), None)
                    if mt and all(clean(f.get(a)) == clean(mt['fields'].get(b)) for a,b in [('street','street'),('postal_code','zipCode'),('city','city')]) and (not f.get(djfield) or not mt['fields'].get(mtfield)):
                        add(role, address, local, 'Rechnungs-/Lieferauswahl aus Shopware nach GC-Bridge und Microtech übernehmen.')
        if not operations or len(operations) > 24:
            return []
        return [dict(title='Shopware-Zuordnungen übernehmen', reason='', certainty='clear', questions=[], evidence=evidence, operations=operations)]
