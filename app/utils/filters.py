from datetime import datetime

def date_filter(value, format='%Y-%m-%d'):
    if isinstance(value, str):
        if value == 'now':
            return datetime.now().strftime(format)
        try:
            return datetime.strptime(value, '%Y-%m-%d').strftime(format)
        except:
            return value

    if isinstance(value, datetime):
        return value.strftime(format)

    return value