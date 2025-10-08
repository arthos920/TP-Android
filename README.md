xpath = f"""
//div[
    (translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') = '{user_name.lower()}'
    or starts-with(translate(normalize-space(text()), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), concat('{user_name.lower()}', ' (')))
    and @data-id='option-selector'
]
"""