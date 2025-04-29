.PHONY: all clean

all: build/presentation.pdf

clean:
	$(RM) -r build

build/presentation.pdf: build/presentation.tex
	latexmk -g -xelatex -output-directory=$(@D) -jobname=$(@F:.pdf=) $(@:.pdf=.tex) < /dev/null

build/presentation.tex: meta.yaml header.tex build/parts/.done
	mkdir -p $(@D)
	pandoc --standalone -t beamer --slide-level=2 -o $@.tmp --metadata-file=meta.yaml --include-in-header=header.tex build/parts/*.md
#	sed -e 's,\\frame{\\titlepage},\\maketitle,' -i $@.tmp
	mv $@.tmp $@

build/parts/.done: shell.py commands.yaml
	$(RM) -r $(@D)
	mkdir -p $(@D)
	touch $@.tmp
	./shell.py -o $(@D) -i commands.yaml
	mv $@.tmp $@
