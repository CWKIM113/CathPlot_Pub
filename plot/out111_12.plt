set encoding utf8
set terminal windows title 'out111_12' font 'Malgun Gothic,11' size 1000,700
unset link y2
set logscale x
set logscale y
set logscale y2
set xrange [1:10000]
set yrange [0.1:10]
set y2range [1:1000]
set xtics auto
set ytics auto
set y2tics auto
set mxtics 10
set mytics 10
set my2tics 10
set grid xtics ytics lw 1.5, lw 1.0
set mouse
set border lw 1.5
set lmargin at screen 0.12
set tmargin at screen 0.895
set bmargin at screen 0.18
set rmargin at screen 0.88
set tics scale 2.0, 1.0
set xtics font 'Malgun Gothic,9'
set ytics font 'Malgun Gothic,9'
set y2tics font 'Malgun Gothic,9'
set title "out111" font "Malgun Gothic,14" noenhanced
set xlabel "Time" font "Malgun Gothic,11" noenhanced
set ylabel "pressure" font "Malgun Gothic,11" noenhanced
set y2label "temp2" font "Malgun Gothic,11" noenhanced
set ytics nomirror
unset key
set object 8000 rect from graph 0.6890,0.7891 to graph 0.9888,0.9888 fc rgb 'white' fs solid 1.0 border lc rgb 'black' lw 1.5 front
set arrow 8001 from graph 0.8970,0.9610 to graph 0.9738,0.9610 nohead front lc rgb "black" lw 1.5
set label 13001 "○" at graph 0.9354,0.9610 center front font "Malgun Gothic,9" textcolor rgb "black"
set label 8001 "pressure" at graph 0.8870,0.9610 right front font "Malgun Gothic,9" noenhanced
set arrow 8002 from graph 0.8970,0.9130 to graph 0.9738,0.9130 nohead front lc rgb "red" lw 1.5 dashtype (6,3)
set label 13002 "□" at graph 0.9354,0.9130 center front font "Malgun Gothic,9" textcolor rgb "red"
set label 8002 "PRESS:PRSTNK(1)" at graph 0.8870,0.9130 right front font "Malgun Gothic,9" noenhanced
set arrow 8003 from graph 0.8970,0.8650 to graph 0.9738,0.8650 nohead front lc rgb "blue" lw 1.5 dashtype (1,2)
set label 13003 "▲" at graph 0.9354,0.8650 center front font "Malgun Gothic,9" textcolor rgb "blue"
set label 8003 "temp2" at graph 0.8870,0.8650 right front font "Malgun Gothic,9" noenhanced
set arrow 8004 from graph 0.8970,0.8170 to graph 0.9738,0.8170 nohead front lc rgb "green" lw 1.5 dashtype (6,2,1,2)
set label 13004 "◇" at graph 0.9354,0.8170 center front font "Malgun Gothic,9" textcolor rgb "green"
set label 8004 "TEMPF:PRSTNK(1)" at graph 0.8870,0.8170 right front font "Malgun Gothic,9" noenhanced
$Marker0 << EOD
0 0.1
1 0.5
2 1.5
10 2
50 2.5
100 2.7
200 5
500 8
700 3
900 5
1000 9
EOD
$Marker1 << EOD
1.01 7.215
1.43 7.165
2.19 7.078
3.13 7.004
4.61 6.958
6.81 6.887
10.01 6.786
14.71 6.642
22.01 6.425
32.01 6.104
46.13 5.783
67.74 5.331
99.64 4.729
146.94 3.821
215.14 3.146
315.84 2.478
463.93 1.924
680.9 1.473
1000.07 1.182
EOD
$Marker2 << EOD
0 350
1 310
2 330
10 350
50 350
100 340
200 320
500 350
700 360
900 330
1000 320
EOD
$Marker3 << EOD
1.04 308.92
2.04 308.8
3.05 308.75
5.07 308.63
7.12 308.51
10.27 308.26
14.62 307.85
21.83 307.26
32.08 306.7
46.16 306.2
67.8 305.53
100.43 304.56
146.63 303.26
215.84 301.34
316.44 298.69
464.44 295.57
681.44 292.11
1000.42 288.12
1467.79 260.34
EOD
plot \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):2 notitle axes x1y1 with lines lw 1.5 lc rgb "black", \
$Marker0 using 1:2 notitle axes x1y1 with points pt 6 ps 1.0 lc rgb "black", \
"temp_sorted/out111_sortedX0.dat" using ($1+0.0):5 notitle axes x1y1 with lines lw 1.5 lc rgb "red" dashtype (6,3), \
$Marker1 using 1:2 notitle axes x1y1 with points pt 4 ps 1.0 lc rgb "red", \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):5 notitle axes x1y2 with lines lw 1.5 lc rgb "blue" dashtype (1,2), \
$Marker2 using 1:2 notitle axes x1y2 with points pt 9 ps 1.0 lc rgb "blue", \
"temp_sorted/PZR_Para_sortedX0.dat" using ($1+0.0):8 notitle axes x1y2 with lines lw 1.5 lc rgb "green" dashtype (6,2,1,2), \
$Marker3 using 1:2 notitle axes x1y2 with points pt 12 ps 1.0 lc rgb "green"

pause mouse close