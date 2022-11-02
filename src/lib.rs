use image::{GenericImageView};
use pyo3::prelude::*;

fn get_str_ascii(intent :u8)-> &'static str {
    let index = intent / 32;
    let ascii = [" ", ".", ",", "-", "~", "+", "=", "@"];
    return ascii[index as usize];
}

#[pyfunction]
fn get_image(dir: &str, scale: u32) -> PyResult<Vec<Vec<&str>>> {
    let img = image::open(dir).unwrap();
    let (width,height) = img.dimensions();
    let mut canvas: Vec<Vec<&str>> = Vec::new();

    for y in 0..height {
        let mut row: Vec<&str> = Vec::new();
        for x in 0..width {
            if y % (scale * 2) == 0 && x % scale == 0 {
                let pix = img.get_pixel(x, y);
                let mut intent = pix[0] / 3 + pix[1] / 3 + pix[2] / 3;
                if pix[3] == 0 {
                    intent = 0;
                }
                row.push(get_str_ascii(intent));
            }
        }
        if y % (scale * 2) == 0 {
            row.push("");
        }
        canvas.push(row);
    }

    Ok(canvas)
}

/// A Python module implemented in Rust.
#[pymodule]
fn ascii_art(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(get_image, m)?)?;
    Ok(())
}