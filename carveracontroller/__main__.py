from carveracontroller.main import main, init_lang, Lang

# tr is used throughout the kivvy .kv definition files
# thus kivy expects it be availiable from the caller
default_lang = init_lang()
tr = Lang(default_lang)

main()
