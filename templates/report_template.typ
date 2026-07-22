// Helper que o writer Typst do pandoc emite para "---" do Markdown (#horizontalrule).
// O template padrão do pandoc o define; como este template é customizado, precisamos
// defini-lo aqui — sem isso, qualquer relatório com linha horizontal falha ao compilar.
#let horizontalrule = line(length: 100%, stroke: 0.5pt + gray)

#set page(
  paper: "a4",
  margin: (top: 2.5cm, bottom: 2.5cm, left: 2cm, right: 2cm),
  numbering: "1 / 1",
)
#set text(font: "Libertinus Serif", size: 11pt, lang: "pt")
#set heading(numbering: none)
#show heading.where(level: 1): set text(size: 18pt, weight: "bold")
#show heading.where(level: 2): set text(size: 14pt, weight: "bold")

#align(center)[
  #v(8cm)
  #text(size: 26pt, weight: "bold")[__TITLE__]
  #v(1.5em)
  #text(size: 14pt, fill: gray)[__AUTHOR__]
  #v(0.5em)
  #text(size: 12pt, fill: gray)[__DATE__]
]
#pagebreak()

__BODY__
