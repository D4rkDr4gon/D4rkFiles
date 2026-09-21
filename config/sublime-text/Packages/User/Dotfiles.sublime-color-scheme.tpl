{
    "name": "Dotfiles",
    "author": "Custom",
    "globals":
    {
        "background": "@background@",
        "foreground": "@foreground@",
        "caret": "@primary@",
        "selection": "@secondary@",
        "selection_border": "@primary@",
        "line_highlight": "@chip_battery@",
        "gutter": "@background@",
        "gutter_foreground": "@text_muted@",
        "inactive_selection": "@chip_battery@"
    },

    "rules":
    [
        {
            "name": "Comment",
            "scope": "comment",
            "foreground": "#666666",
            "font_style": "italic"
        },
        {
            "name": "String",
            "scope": "string",
            "foreground": "#ff6666"
        },
        {
            "name": "Number",
            "scope": "constant.numeric",
            "foreground": "#ff4d4d"
        },
        {
            "name": "Keyword",
            "scope": "keyword",
            "foreground": "#d32f2f",
            "font_style": "bold"
        },
        {
            "name": "Function",
            "scope": "entity.name.function",
            "foreground": "#ff5c5c"
        },
        {
            "name": "Variable",
            "scope": "variable",
            "foreground": "#c5c8c6"
        },
        {
            "name": "Type",
            "scope": "storage.type",
            "foreground": "#ff3333"
        }
    ]
}
