/* *****************************************************************************
 Copyright 2010 The Fatiando a Terra Development Team

 This file is part of Fatiando a Terra.

 Fatiando a Terra is free software: you can redistribute it and/or modify
 it under the terms of the GNU Lesser General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 Fatiando a Terra is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU Lesser General Public License for more details.

 You should have received a copy of the GNU Lesser General Public License
 along with Fatiando a Terra.  If not, see <http://www.gnu.org/licenses/>.
 **************************************************************************** */

/* **************************************************************************

 This module contains a set of functions that calculate the travel times of
 seismic waves.

 Author: Leonardo Uieda
 Date: 29 April 2010

 **************************************************************************** */

#include <math.h>
#include "traveltime.h"

/* Calculate the travel time inside a square cell assuming the ray is a straight
 * line */
double cartesian_straight(double slowness, double x1, double y1,
						  double x2, double y2, double x_src, double y_src,
						  double x_rec, double y_rec)
{

    double maxx, maxy, minx, miny;
    double xps[6], yps[6], xp, yp;
    double crossingx[6], crossingy[6];
    double distance, a_ray, b_ray;
    int i, j, crossingsize, inside;
    short duplicate;

    /* Some aux variables to avoid calling max and min too much */
    maxx = MAX(x_src, x_rec);
    maxy = MAX(y_src, y_rec);
    minx = MIN(x_src, x_rec);
    miny = MIN(y_src, y_rec);

    /* Check if the cell is with the rectangle with the ray path as a
     * diagonal. If not, then the ray doesn't go through the cell. */
    if(x2 < minx || x1 > maxx || y2 < miny || y1 > maxy)
    {
        return 0;
    }

    /* Vertical case */
    if((x_rec - x_src) == 0)
    {

        /* Find the places where the ray intersects the cell */
        xps[0] = x_rec;
        xps[1] = x_rec;
        xps[2] = x_rec;
        xps[3] = x_rec;

        yps[0] = y_rec;
        yps[1] = y_src;
        yps[2] = y1;
        yps[3] = y2;

        crossingsize = 4;
    }

    /* Horizontal case */
    else if((y_rec - y_src) == 0)
    {
        /* Find the places where the ray intersects the cell */
        xps[0] = x_rec;
        xps[1] = x_src;
        xps[2] = x1;
        xps[3] = x2;

        yps[0] = y_rec;
        yps[1] = y_rec;
        yps[2] = y_rec;
        yps[3] = y_rec;

        crossingsize = 4;
    }
    else
    {
        a_ray = (double)(y_rec - y_src)/(x_rec - x_src);

        b_ray = y_src - a_ray*x_src;

        /* Find the places where the ray intersects the cell */
        xps[0] = x1;
        xps[1] = x2;

        yps[0] = a_ray*x1 + b_ray;
        yps[1] = a_ray*x2 + b_ray;

        yps[2] = y1;
        yps[3] = y2;

        xps[2] = (double)(y1 - b_ray)/a_ray;
        xps[3] = (double)(y2 - b_ray)/a_ray;


        /* Add the src and rec locations so that the travel time of a src or rec
         * inside a cell is accounted for */
        xps[4] = x_src;
        xps[5] = x_rec;
        yps[4] = y_src;
        yps[5] = y_rec;

        crossingsize = 6;
    }

    /* Find out how many points are inside both the cell and the rectangle with
     * the ray path as a diagonal */
    inside = 0;
    for(i=0; i < crossingsize; i++)
    {

        xp = xps[i];
        yp = yps[i];

        if( (xp <= x2 && xp >= x1 && yp <= y2 && yp >= y1) &&
            (xp <= maxx && xp >= minx && yp <= maxy && yp >= miny))
        {

            duplicate = 0;

            for(j=0; j < inside; j++)
            {
                if(crossingx[j] == xp && crossingy[j] == yp)
                {
                    duplicate = 1;

                    break;
                }
            }

            if(!duplicate)
            {
                crossingx[inside] = xp;

                crossingy[inside] = yp;

                inside++;
            }
        }
    }

    if(inside < 2)
    {
        return 0;
    }

    if(inside > 2)
    {
        return -1;
    }

    distance = sqrt((crossingx[1] - crossingx[0])*
    				(crossingx[1] - crossingx[0]) +
                    (crossingy[1] - crossingy[0])*
                    (crossingy[1] - crossingy[0]));

    return distance*slowness;

}
